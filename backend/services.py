"""Resource backends for the console.

Three concerns live here:

* :mod:`Docker`  – compute instances (real Docker with graceful fallback)
* :mod:`MySQL`   – the SQL query console
* :mod:`Storage` – per-user object storage on the local filesystem

Every backend degrades gracefully: when Docker or MySQL is unavailable the
console returns a clear error instead of crashing.
"""

from __future__ import annotations

import mimetypes
import os
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Optional

import config
import db
from security import AuthError, Forbidden

# ===========================================================================
# Activity / audit trail
# ===========================================================================

def log_activity(
    user: dict[str, Any],
    action: str,
    resource: Optional[str] = None,
    status: str = "Success",
) -> None:
    try:
        db.execute(
            "INSERT INTO nimbus_activity (user_id, username, action, resource, status) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user.get("id"), user.get("name") or user.get("username", "unknown"),
             action, resource, status),
        )
    except Exception:
        # Auditing must never break the primary operation.
        pass


# ===========================================================================
# Docker compute backend
# ===========================================================================

class DockerUnavailable(RuntimeError):
    """Docker is not installed or the daemon cannot be reached."""


_OS_IMAGES = {
    "ubuntu": "ubuntu:latest",
    "ubuntu 22.04": "ubuntu:latest",
    "ubuntu 24.04": "ubuntu:latest",
    "debian": "debian:latest",
    "debian 12": "debian:latest",
    "alpine": "alpine:latest",
    "alpine linux": "alpine:latest",
    "amazon linux": "amazonlinux:latest",
    "amazonlinux": "amazonlinux:latest",
    "centos": "centos:stream9",
    "centos stream": "centos:stream9",
}

_STATUS_MAP = {
    "running": "Running",
    "exited": "Stopped",
    "created": "Stopped",
    "paused": "Stopped",
    "dead": "Stopped",
    "removing": "Stopped",
    "restarting": "Running",
}


def _docker_client():
    try:
        import docker  # imported lazily so the server boots without Docker
    except ImportError as exc:  # pragma: no cover
        raise DockerUnavailable("The docker Python SDK is not installed.") from exc
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        raise DockerUnavailable(f"Docker daemon is not reachable: {exc}") from exc


def docker_available() -> bool:
    try:
        _docker_client()
        return True
    except DockerUnavailable:
        return False


def resolve_image(os_name: str) -> str:
    key = (os_name or "").strip().lower()
    if key not in _OS_IMAGES:
        raise AuthError(f"Unsupported operating system: {os_name}")
    return _OS_IMAGES[key]


def _valid_instance_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", name or ""))


def valid_database_name(name: str) -> bool:
    """Console database names are restricted to a conservative character set.

    Besides keeping generated SQL identifiers predictable this also guarantees
    names are safe to embed in markup / javascript handlers in the front end.
    """
    return bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", name or ""))


def normalize_status(raw: str) -> str:
    return _STATUS_MAP.get((raw or "").lower(), "Stopped")


def _container_ip(container) -> Optional[str]:
    try:
        networks = container.attrs["NetworkSettings"]["Networks"]
        for net in networks.values():
            ip = net.get("IPAddress")
            if ip:
                return ip
    except Exception:  # noqa: BLE001
        pass
    return None


def _docker_name(owner_id: int, name: str) -> str:
    return f"nimbus-{owner_id}-{name}"


def _instance_dict(row: dict[str, Any], container=None) -> dict[str, Any]:
    status = normalize_status(container.status) if container is not None else row["status"]
    ip = _container_ip(container) if container is not None else row.get("ip") or "—"
    created = row.get("created_at")
    return {
        "id": row["id"],
        "name": row["name"],
        "instanceId": f"i-{(row.get('container_id') or '')[:12] or 'pending'}",
        "os": row["os"],
        "ip": ip or "—",
        "status": status,
        "cpu": float(row["cpu"]),
        "ram": int(row["ram_gb"]),
        "storage": int(row["storage_gb"]),
        "created": created.strftime("%b %d, %Y") if hasattr(created, "strftime") else str(created),
        "owner": row.get("owner_name") or row.get("username") or "",
    }


def list_instances(user: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the caller's instances, syncing live Docker status into MySQL."""
    params: tuple = ()
    where = "WHERE i.owner_id = %s"
    params = (user["id"],)
    if user["role"] == "Administrator":
        where = ""
        params = ()
    rows = db.query_all(
        f"""
        SELECT i.*, u.username AS owner_name
        FROM nimbus_instances i JOIN nimbus_users u ON u.id = i.owner_id
        {where}
        ORDER BY i.created_at DESC
        """,
        params,
        dictionary=True,
    )

    client = None
    try:
        client = _docker_client()
    except DockerUnavailable:
        client = None

    result = []
    for row in rows:
        container = None
        if client is not None:
            for candidate in (row.get("container_id"), _docker_name(row["owner_id"], row["name"])):
                if not candidate:
                    continue
                try:
                    container = client.containers.get(candidate)
                    break
                except Exception:  # noqa: BLE001
                    continue
        entry = _instance_dict(row, container)
        if container is not None:
            db.execute(
                "UPDATE nimbus_instances SET status = %s, ip = %s WHERE id = %s",
                (entry["status"], None if entry["ip"] == "—" else entry["ip"], row["id"]),
            )
        result.append(entry)
    return result


def create_instance(
    user: dict[str, Any],
    name: str,
    os_name: str,
    cpu: float,
    ram_gb: int,
    storage_gb: int,
) -> dict[str, Any]:
    if not _valid_instance_name(name):
        raise AuthError("Invalid instance name. Use letters, digits, '.', '_' or '-'.")

    existing = db.query_one(
        "SELECT id FROM nimbus_instances WHERE owner_id = %s AND name = %s",
        (user["id"], name),
    )
    if existing:
        raise AuthError("An instance with this name already exists.")

    if not (config.MIN_CPU <= cpu <= config.MAX_CPU):
        raise AuthError(f"CPU must be between {config.MIN_CPU} and {config.MAX_CPU} cores.")
    if not (config.MIN_RAM_GB <= ram_gb <= config.MAX_RAM_GB):
        raise AuthError(f"RAM must be between {config.MIN_RAM_GB} and {config.MAX_RAM_GB} GB.")
    if not (config.MIN_STORAGE_GB <= storage_gb <= config.MAX_STORAGE_GB):
        raise AuthError(
            f"Storage must be between {config.MIN_STORAGE_GB} and {config.MAX_STORAGE_GB} GB."
        )

    image = resolve_image(os_name)
    client = _docker_client()

    try:
        client.images.get(image)
    except Exception:  # noqa: BLE001 - image not present locally
        try:
            client.images.pull(image)
        except Exception as exc:  # noqa: BLE001
            raise DockerUnavailable(f"Could not obtain image '{image}': {exc}") from exc

    docker_name = _docker_name(user["id"], name)
    volume_name = f"{docker_name}-data"
    try:
        # Reuse a retained volume from a previous instance of the same name,
        # otherwise create a fresh one.
        volume = client.volumes.get(volume_name)
        volume_created = False
    except Exception:  # noqa: BLE001 - volume does not exist yet
        volume = client.volumes.create(name=volume_name)
        volume_created = True

    try:
        container = client.containers.run(
            image=image,
            name=docker_name,
            command=["sh", "-c", "while true; do sleep 3600; done"],
            detach=True,
            tty=True,
            stdin_open=True,
            nano_cpus=int(cpu * 1_000_000_000),
            mem_limit=f"{ram_gb * 1024}m",
            volumes={volume.name: {"bind": "/data", "mode": "rw"}},
            labels={
                "cloud.instance": "true",
                "cloud.owner": user["username"],
                "cloud.owner_id": str(user["id"]),
                "cloud.os": os_name,
                "cloud.storage_gb": str(storage_gb),
            },
            restart_policy={"Name": "unless-stopped"},
        )
    except Exception as exc:  # noqa: BLE001
        if volume_created:
            try:
                volume.remove(force=True)
            except Exception:  # noqa: BLE001
                pass
        raise DockerUnavailable(f"Instance creation failed: {exc}") from exc

    try:
        row_id = db.execute(
            """
            INSERT INTO nimbus_instances
                (owner_id, name, container_id, os, cpu, ram_gb, storage_gb, status, ip)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user["id"], name, container.short_id, os_name, cpu, ram_gb, storage_gb,
                normalize_status(container.status), _container_ip(container),
            ),
        )
    except Exception:
        # Never leave an orphaned container (or a freshly created volume)
        # behind when the metadata write fails.
        try:
            container.remove(force=True)
        except Exception:  # noqa: BLE001
            pass
        if volume_created:
            try:
                volume.remove(force=True)
            except Exception:  # noqa: BLE001
                pass
        raise

    row = db.query_one(
        """
        SELECT i.*, u.username AS owner_name FROM nimbus_instances i
        JOIN nimbus_users u ON u.id = i.owner_id WHERE i.id = %s
        """,
        (row_id,),
        dictionary=True,
    )
    log_activity(user, "Instance Created", name)
    return _instance_dict(row, container)


def _owned_instance(user: dict[str, Any], instance_id: int) -> dict[str, Any]:
    row = db.query_one(
        "SELECT * FROM nimbus_instances WHERE id = %s", (instance_id,), dictionary=True
    )
    if not row:
        raise AuthError("Instance not found.")
    if row["owner_id"] != user["id"] and user["role"] != "Administrator":
        raise Forbidden("You do not have access to this instance.")
    return row


def control_instance(user: dict[str, Any], instance_id: int, action: str) -> dict[str, Any]:
    row = _owned_instance(user, instance_id)
    client = _docker_client()
    container = None
    for candidate in (row.get("container_id"), _docker_name(row["owner_id"], row["name"])):
        try:
            container = client.containers.get(candidate)
            break
        except Exception:  # noqa: BLE001
            continue
    if container is None:
        db.execute("UPDATE nimbus_instances SET status = 'Stopped' WHERE id = %s", (instance_id,))
        raise AuthError("The underlying container no longer exists.")

    if action == "start":
        container.start()
        label = "started"
    elif action == "stop":
        container.stop(timeout=10)
        label = "stopped"
    elif action == "restart":
        container.restart(timeout=10)
        label = "restarted"
    else:
        raise AuthError("Unsupported action.")

    container.reload()
    status = normalize_status(container.status)
    db.execute(
        "UPDATE nimbus_instances SET status = %s, ip = %s WHERE id = %s",
        (status, _container_ip(container), instance_id),
    )
    log_activity(user, f"Instance {label.capitalize()}", row["name"])
    fresh = db.query_one(
        """
        SELECT i.*, u.username AS owner_name FROM nimbus_instances i
        JOIN nimbus_users u ON u.id = i.owner_id WHERE i.id = %s
        """,
        (instance_id,),
        dictionary=True,
    )
    return _instance_dict(fresh, container)


def delete_instance(user: dict[str, Any], instance_id: int, delete_data: bool = False) -> None:
    row = _owned_instance(user, instance_id)
    client = _docker_client()
    try:
        container = None
        for candidate in (row.get("container_id"), _docker_name(row["owner_id"], row["name"])):
            try:
                container = client.containers.get(candidate)
                break
            except Exception:  # noqa: BLE001
                continue
        if container is not None:
            container.remove(force=True)
        if delete_data:
            try:
                client.volumes.get(f"{_docker_name(row['owner_id'], row['name'])}-data").remove(force=True)
            except Exception:  # noqa: BLE001
                pass
    except DockerUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DockerUnavailable(f"Could not remove the container: {exc}") from exc

    db.execute("DELETE FROM nimbus_instances WHERE id = %s", (instance_id,))
    log_activity(user, "Instance Deleted", row["name"])


def list_running_containers(user: dict[str, Any]) -> list[dict[str, Any]]:
    """Containers the caller may open a terminal on."""
    client = _docker_client()
    containers = client.containers.list(
        all=False, filters={"label": "cloud.instance=true"}
    )
    result = []
    for container in containers:
        labels = container.labels or {}
        owner_id = labels.get("cloud.owner_id")
        if user["role"] != "Administrator" and str(owner_id) != str(user["id"]):
            continue
        result.append(
            {
                "id": container.id,
                "name": container.name,
                "status": normalize_status(container.status),
            }
        )
    return result


def authorize_container(user: dict[str, Any], container_id: str):
    """Return the Docker container if the caller may access it."""
    client = _docker_client()
    try:
        container = client.containers.get(container_id)
    except Exception as exc:  # noqa: BLE001
        raise AuthError(f"Container not found: {container_id}") from exc
    labels = container.labels or {}
    if labels.get("cloud.instance") != "true":
        raise AuthError("This container is not a cloud instance.")
    if user["role"] != "Administrator" and str(labels.get("cloud.owner_id")) != str(user["id"]):
        raise Forbidden("You do not have access to this container.")
    return client, container


# ===========================================================================
# MySQL query backend
# ===========================================================================

class SqlError(RuntimeError):
    """A user-facing SQL error (bad query or unreachable database)."""


_READ_ONLY_KEYWORDS = ("select", "show", "describe", "desc", "explain", "with", "use")

# Statements that read or write the database server's filesystem, or that can
# be abused to exhaust the server, are never allowed through the SQL console.
_FILE_STATEMENTS_RE = re.compile(r"\b(into\s+(out|dump)file|load_file|load\s+data)\b", re.I)
_DOS_FUNCTIONS_RE = re.compile(r"\b(benchmark|sleep)\s*\(", re.I)
# Console metadata (password hashes, session tokens) must never be reachable
# from the SQL console by non-administrators.
_METADATA_RE = re.compile(r"\bnimbus_[a-z0-9_]*\b", re.I)
_SYSTEM_SCHEMAS_RE = re.compile(r"\b(information_schema|performance_schema|mysql|sys)\s*\.", re.I)


def _strip_sql_literals(query: str) -> str:
    """Remove string literals and comments so keyword scans cannot be fooled.

    Only single and double quotes are treated as string delimiters.  Backticks
    are MySQL *identifier* quotes, so their contents are meaningful and must be
    preserved (otherwise ``SELECT * FROM `nimbus_sessions` `` could slip past the
    metadata guard).  The contents of quoted strings and comments are replaced
    with spaces.
    """
    out: list[str] = []
    i = 0
    n = len(query)
    while i < n:
        ch = query[i]
        nxt = query[i + 1] if i + 1 < n else ""
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n:
                if query[i] == "\\" and quote in ("'", '"'):
                    i += 2
                    continue
                if query[i] == quote:
                    if quote in ("'", '"') and i + 1 < n and query[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(" ")
            continue
        if ch == "#":
            while i < n and query[i] != "\n":
                i += 1
            continue
        if ch == "-" and nxt == "-":
            while i < n and query[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (query[i] == "*" and query[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def assert_query_allowed(query: str, user: dict[str, Any]) -> None:
    """Reject unsafe SQL before it reaches MySQL."""
    cleaned = _strip_sql_literals(query or "")
    if _FILE_STATEMENTS_RE.search(cleaned):
        raise SqlError("Statements that read or write server files are not permitted.")
    if _DOS_FUNCTIONS_RE.search(cleaned):
        raise SqlError("Sleep/benchmark functions are not permitted.")
    if user.get("role") != "Administrator":
        if _METADATA_RE.search(cleaned):
            raise Forbidden("Access to console metadata tables is not permitted.")
        if _SYSTEM_SCHEMAS_RE.search(cleaned):
            raise Forbidden("Access to system schemas is not permitted.")


def is_read_only(query: str) -> bool:
    first = re.sub(r"^\s*(/\*.*?\*/\s*)*", "", query, flags=re.S).strip().split(None, 1)
    if not first:
        return True
    return first[0].lower() in _READ_ONLY_KEYWORDS


def _sanitize_identifier(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]", "_", (value or "").strip())
    value = re.sub(r"_+", "_", value).strip("_")
    if not value or not re.match(r"^[a-zA-Z]", value):
        value = f"db_{value}" if value else ""
    return value[:60]


def provision_database(schema_name: str) -> tuple[str, bool]:
    """Try to create a real MySQL schema.

    Returns ``(effective_schema, created)``.  When the account lacks CREATE
    privileges we fall back to the console's default schema so the SQL console
    still has real data to operate on.
    """
    wanted = _sanitize_identifier(schema_name)
    if not wanted:
        raise AuthError("Invalid database name.")
    connection = None
    cur = None
    try:
        connection = db.connect()
        cur = connection.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{wanted}`")
        connection.commit()
        return wanted, True
    except Exception:  # noqa: BLE001 - privilege/duplicate -> logical fallback
        if connection is not None:
            try:
                connection.rollback()
            except Exception:  # noqa: BLE001
                pass
        return config.MYSQL_DATABASE, False
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:  # noqa: BLE001
                pass
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass


def list_tables(schema_name: str) -> list[str]:
    connection = None
    cur = None
    try:
        connection = db.connect(database=schema_name)
        cur = connection.cursor()
        cur.execute("SHOW TABLES")
        return [row[0] for row in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise SqlError(str(exc)) from exc
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:  # noqa: BLE001
                pass
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass


def run_query(
    schema_name: str,
    query: str,
    max_rows: int = config.MAX_QUERY_ROWS,
    read_only: bool = False,
) -> dict[str, Any]:
    query = (query or "").strip().rstrip(";").strip()
    if not query:
        raise SqlError("Query cannot be empty.")

    connection = None
    cur = None
    started = time.perf_counter()
    try:
        connection = db.connect(database=schema_name)
        cur = connection.cursor(dictionary=True, buffered=True)
        if read_only:
            # Hard server-side guarantee that a read-only role cannot mutate
            # data, even with CTEs or statements the keyword check misses.
            cur.execute("START TRANSACTION READ ONLY")
            # MySQL treats START TRANSACTION READ ONLY as a transaction; the
            # cursor is now inside it.  Statements execute below.
            cur.execute(query)
            read_only_started = True
        else:
            cur.execute(query)
            read_only_started = False

        columns: list[str] = []
        rows: list[Any] = []
        affected = 0
        last_result: dict[str, Any] = {}

        while True:
            if cur.with_rows:
                columns = [d[0] for d in (cur.description or [])]
                fetched = cur.fetchall()
                rows = fetched[:max_rows]
                last_result = {
                    "type": "RESULT",
                    "row_count": len(fetched),
                    "returned_rows": len(rows),
                }
            else:
                affected += cur.rowcount or 0
                last_result = {"type": "OK", "affected_rows": cur.rowcount or 0}
            if cur.nextset() is None:
                break

        if read_only_started:
            connection.rollback()
        elif last_result.get("type") != "RESULT":
            connection.commit()

        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        if last_result.get("type") == "RESULT":
            message = f"{last_result['row_count']} row(s) returned"
        else:
            message = f"OK: {affected} row(s) affected"

        return {
            "columns": columns,
            "rows": rows,
            "row_count": last_result.get("row_count", 0),
            "affected_rows": 0 if read_only else affected,
            "message": message,
            "duration_ms": duration_ms,
        }
    except Exception as exc:  # noqa: BLE001
        if connection is not None:
            try:
                connection.rollback()
            except Exception:  # noqa: BLE001
                pass
        raise SqlError(str(exc)) from exc
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:  # noqa: BLE001
                pass
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass


def resolve_schema(user: dict[str, Any], database_name: Optional[str]) -> str:
    """Map a console database name to a real MySQL schema."""
    if database_name:
        row = None
        if user["role"] == "Administrator":
            row = db.query_one(
                "SELECT schema_name FROM nimbus_databases WHERE name = %s",
                (database_name,),
                dictionary=True,
            )
        if row is None:
            row = db.query_one(
                "SELECT schema_name FROM nimbus_databases WHERE owner_id = %s AND name = %s",
                (user["id"], database_name),
                dictionary=True,
            )
        if row:
            return row["schema_name"]
    return config.MYSQL_DATABASE


# ===========================================================================
# Storage backend
# ===========================================================================

class StorageError(RuntimeError):
    """A user-facing storage error."""


def _safe_name(filename: str) -> str:
    """Reduce an untrusted name to a single safe path component.

    Backslashes are treated as separators (Windows clients) and leading /
    trailing dots and spaces are removed so names such as ``.``, ``..`` or
    ``...`` can never resolve to a directory other than the user's own folder.
    """
    base = os.path.basename((filename or "").replace("\\", "/")).strip()
    base = re.sub(r"[^a-zA-Z0-9._ -]", "_", base)
    base = base.strip(" .")
    if not base or base in (".", ".."):
        base = "file"
    return base[:180]


def _user_dir(user: dict[str, Any]) -> Path:
    return (config.STORAGE_DIR / str(user["id"])).resolve()


def _contained_path(user: dict[str, Any], candidate: Path) -> Path:
    """Return ``candidate`` if it stays inside the user's storage folder."""
    user_dir = _user_dir(user)
    resolved = candidate.resolve()
    if resolved != user_dir and user_dir not in resolved.parents:
        raise StorageError("Invalid path.")
    return resolved


def kind_for(filename: str, content_type: Optional[str] = None) -> str:
    ctype = (content_type or "").lower()
    ext = Path(filename or "").suffix.lower()
    if ctype.startswith("image/") or ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}:
        return "Image"
    if ext == ".pdf" or ctype == "application/pdf":
        return "PDF"
    if ext in {".zip", ".tar", ".gz", ".tgz", ".rar", ".7z"}:
        return "Archive"
    if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        return "Video"
    if ext in {".mp3", ".wav", ".flac", ".ogg"}:
        return "Audio"
    if ext in {".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".xlsx", ".csv", ".ppt", ".pptx"}:
        return "Document"
    return "Other"


def human_size(num_bytes: int) -> str:
    size = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def storage_used(user: dict[str, Any]) -> int:
    row = db.query_one(
        "SELECT COALESCE(SUM(size_bytes), 0) AS used FROM nimbus_files WHERE owner_id = %s",
        (user["id"],),
        dictionary=True,
    )
    return int(row["used"]) if row else 0


def list_files(user: dict[str, Any]) -> list[dict[str, Any]]:
    where, params = ("WHERE f.owner_id = %s", (user["id"],))
    if user["role"] == "Administrator":
        where, params = ("", ())
    rows = db.query_all(
        f"""
        SELECT f.*, u.name AS owner_name
        FROM nimbus_files f JOIN nimbus_users u ON u.id = f.owner_id
        {where} ORDER BY f.created_at DESC
        """,
        params,
        dictionary=True,
    )
    return [_file_dict(row) for row in rows]


def _file_dict(row: dict[str, Any]) -> dict[str, Any]:
    created = row.get("created_at")
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["kind"],
        "size": "—" if row["kind"] == "Folder" else human_size(row["size_bytes"]),
        "sizeBytes": int(row["size_bytes"]),
        "date": created.strftime("%b %d, %Y") if hasattr(created, "strftime") else str(created),
        "owner": row.get("owner_name") or "",
    }


def save_folder(user: dict[str, Any], name: str) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise AuthError("Folder name is required.")
    folder_path = _contained_path(user, _user_dir(user) / _safe_name(name))
    folder_path.mkdir(parents=True, exist_ok=True)
    row_id = db.execute(
        "INSERT INTO nimbus_files (owner_id, name, kind, size_bytes, stored_path) "
        "VALUES (%s, %s, 'Folder', 0, %s)",
        (user["id"], _safe_name(name), str(folder_path)),
    )
    log_activity(user, "Folder Created", name)
    row = db.query_one(
        "SELECT f.*, u.name AS owner_name FROM nimbus_files f JOIN nimbus_users u "
        "ON u.id = f.owner_id WHERE f.id = %s",
        (row_id,),
        dictionary=True,
    )
    return _file_dict(row)


def save_upload(user: dict[str, Any], filename: str, stream: BinaryIO, content_type: Optional[str] = None) -> dict[str, Any]:
    safe = _safe_name(filename)
    user_dir = _user_dir(user)
    user_dir.mkdir(parents=True, exist_ok=True)
    target = _contained_path(user, user_dir / f"{uuid.uuid4().hex}_{safe}")

    written = 0
    used_before = storage_used(user)
    try:
        with open(target, "wb") as out:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if used_before + written > config.QUOTA_BYTES:
                    raise StorageError("Storage quota exceeded.")
                if written > config.MAX_UPLOAD_BYTES:
                    raise StorageError("File exceeds the maximum upload size.")
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    row_id = db.execute(
        "INSERT INTO nimbus_files (owner_id, name, kind, size_bytes, stored_path) "
        "VALUES (%s, %s, %s, %s, %s)",
        (user["id"], safe, kind_for(safe, content_type), written, str(target)),
    )
    log_activity(user, "File Uploaded", safe)
    row = db.query_one(
        "SELECT f.*, u.name AS owner_name FROM nimbus_files f JOIN nimbus_users u "
        "ON u.id = f.owner_id WHERE f.id = %s",
        (row_id,),
        dictionary=True,
    )
    return _file_dict(row)


def _owned_file(user: dict[str, Any], file_id: int) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM nimbus_files WHERE id = %s", (file_id,), dictionary=True)
    if not row:
        raise AuthError("File not found.")
    if row["owner_id"] != user["id"] and user["role"] != "Administrator":
        raise Forbidden("You do not have access to this file.")
    return row


def get_file(user: dict[str, Any], file_id: int) -> dict[str, Any]:
    return _owned_file(user, file_id)


def _within_storage(path: Path) -> bool:
    root = config.STORAGE_DIR.resolve()
    resolved = path.resolve()
    return resolved != root and root in resolved.parents


def delete_file(user: dict[str, Any], file_id: int) -> None:
    row = _owned_file(user, file_id)
    path = Path(row["stored_path"])
    try:
        if not _within_storage(path):
            raise StorageError("Refusing to remove a path outside the storage directory.")
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
    except StorageError:
        raise
    except Exception:  # noqa: BLE001
        pass
    db.execute("DELETE FROM nimbus_files WHERE id = %s", (file_id,))
    log_activity(user, "File Deleted", row["name"])


def storage_summary(user: dict[str, Any]) -> dict[str, Any]:
    used = storage_used(user)
    return {
        "usedBytes": used,
        "quotaBytes": config.QUOTA_BYTES,
        "usedLabel": human_size(used),
        "quotaLabel": human_size(config.QUOTA_BYTES),
        "percent": round(used / config.QUOTA_BYTES * 100, 1) if config.QUOTA_BYTES else 0,
    }


def guess_content_type(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def now_label() -> str:
    return datetime.now().strftime("%b %d, %Y, %I:%M %p")
