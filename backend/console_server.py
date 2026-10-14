"""Nimbus Console — unified FastAPI backend.

This single application connects the Nimbus frontend to the backend resource
modules:

* user accounts, sessions and per-user resource ownership (MySQL)
* compute instances backed by Docker (see ``services.py``)
* object storage on the local filesystem
* a MySQL SQL query console
* an activity / audit trail

Run it with::

    uvicorn console_server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import config
import db
import security
import services
from security import AuthError, Forbidden

# ===========================================================================
# Application lifecycle
# ===========================================================================

def _seed_admin() -> None:
    row = db.query_one("SELECT COUNT(*) AS total FROM nimbus_users", dictionary=True)
    if row and int(row["total"]) == 0:
        db.execute(
            "INSERT INTO nimbus_users (name, username, email, password_hash, role) "
            "VALUES (%s, %s, %s, %s, 'Administrator')",
            (
                "Administrator",
                "admin",
                "admin@nimbus.local",
                security.hash_password("admin123"),
            ),
        )
        print("[nimbus] Seeded default administrator account 'admin' (change its password on first login)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        db.init_schema()
        security.purge_expired_sessions()
        _seed_admin()
        print(f"[nimbus] MySQL ready at {config.MYSQL_HOST}:{config.MYSQL_PORT}/{config.MYSQL_DATABASE}")
    except Exception as exc:  # noqa: BLE001
        print(f"[nimbus] WARNING: database not ready at startup: {exc}")
    print(f"[nimbus] Serving frontend from {config.FRONTEND_DIR}")
    yield


app = FastAPI(title="Nimbus Console API", version="2.0.0", lifespan=lifespan)


# ===========================================================================
# Error handlers
# ===========================================================================

def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message, "detail": message})


@app.exception_handler(Forbidden)
async def _forbidden_handler(_request: Request, exc: Forbidden):
    return _error(403, str(exc))


@app.exception_handler(AuthError)
async def _auth_handler(_request: Request, exc: AuthError):
    return _error(400, str(exc))


@app.exception_handler(security.RateLimited)
async def _rate_handler(_request: Request, exc: security.RateLimited):
    return _error(429, str(exc))


@app.exception_handler(services.DockerUnavailable)
async def _docker_handler(_request: Request, exc: services.DockerUnavailable):
    return _error(503, f"Compute service unavailable: {exc}")


@app.exception_handler(services.SqlError)
async def _sql_handler(_request: Request, exc: services.SqlError):
    return _error(400, f"SQL error: {exc}")


@app.exception_handler(services.StorageError)
async def _storage_handler(_request: Request, exc: services.StorageError):
    return _error(400, str(exc))


@app.exception_handler(db.DatabaseUnavailable)
async def _db_handler(_request: Request, exc: db.DatabaseUnavailable):
    return _error(503, f"Database unavailable: {exc}")


# ===========================================================================
# Auth dependency
# ===========================================================================

def current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(config.SESSION_COOKIE)
    user = security.user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user


def _set_session_cookie(response: JSONResponse, token: str) -> None:
    response.set_cookie(
        key=config.SESSION_COOKIE,
        value=token,
        max_age=config.SESSION_TTL_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
        path="/",
    )


# ===========================================================================
# Request models
# ===========================================================================

class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=3, max_length=60)
    email: str = Field(min_length=3, max_length=190)
    password: str = Field(min_length=1)
    role: str = "Viewer"


class LoginRequest(BaseModel):
    identifier: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    password: str


class InstanceCreate(BaseModel):
    name: str
    os: str = "Ubuntu 22.04"
    cpu: float = 1
    ram: int = 1
    storage: int = 10


class DatabaseCreate(BaseModel):
    name: str
    type: str = "MySQL"
    port: int = 3306
    username: Optional[str] = None
    password: Optional[str] = None


class QueryRequest(BaseModel):
    database: Optional[str] = None
    query: str
    max_rows: int = Field(default=config.MAX_QUERY_ROWS, ge=1, le=5000)


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    notifyEnabled: Optional[bool] = None


class PasswordChange(BaseModel):
    current: str
    new: str


class FolderCreate(BaseModel):
    name: str


# ===========================================================================
# Auth endpoints
# ===========================================================================

@app.post("/api/auth/signup", status_code=201)
def signup(payload: SignupRequest):
    username = payload.username.strip()
    name = payload.name.strip()
    email = payload.email.strip().lower()
    role = payload.role if payload.role in config.SELF_SIGNUP_ROLES else config.DEFAULT_SIGNUP_ROLE
    if not name:
        raise AuthError("Name is required.")
    security.validate_username(username)
    security.validate_email(email)
    security.validate_password(payload.password)

    if db.query_one("SELECT id FROM nimbus_users WHERE username = %s", (username,)):
        raise AuthError("That username is already taken.")
    if db.query_one("SELECT id FROM nimbus_users WHERE email = %s", (email,)):
        raise AuthError("That email is already registered.")

    user_id = db.execute(
        "INSERT INTO nimbus_users (name, username, email, password_hash, role) "
        "VALUES (%s, %s, %s, %s, %s)",
        (name, username, email, security.hash_password(payload.password), role),
    )
    token = security.create_session(user_id)
    user = security.get_user_by_id(user_id)
    services.log_activity(user, "Account Created", username)

    response = JSONResponse(status_code=201, content={"user": security.public_user(user)})
    _set_session_cookie(response, token)
    return response


@app.post("/api/auth/login")
def login(payload: LoginRequest):
    identifier = (payload.identifier or payload.username or payload.email or "").strip()
    if not identifier:
        raise AuthError("Enter your email or username.")

    locked = security.login_throttle.is_locked(identifier)
    if locked:
        raise security.RateLimited(
            f"Too many failed attempts. Try again in {locked} second(s)."
        )

    user = security.authenticate(identifier, payload.password)
    if not user:
        security.login_throttle.register_failure(identifier)
        services.log_activity(
            {"id": None, "name": identifier},
            "Sign In Failed",
            identifier,
            status="Failed",
        )
        # Generic message: never reveal whether the account exists.
        raise AuthError("Invalid credentials. Please try again.")

    security.login_throttle.reset(identifier)
    token = security.create_session(user["id"])
    services.log_activity(user, "Signed In", user["username"])
    response = JSONResponse(content={"user": security.public_user(user)})
    _set_session_cookie(response, token)
    return response


@app.post("/api/auth/logout")
def logout(request: Request):
    token = request.cookies.get(config.SESSION_COOKIE)
    security.destroy_session(token)
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(config.SESSION_COOKIE, path="/")
    return response


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(current_user)):
    return {"user": security.public_user(user)}


# ===========================================================================
# Compute instances
# ===========================================================================

@app.get("/api/instances")
def get_instances(user: dict[str, Any] = Depends(current_user)):
    return {"instances": services.list_instances(user)}


@app.post("/api/instances", status_code=201)
def create_instance(payload: InstanceCreate, user: dict[str, Any] = Depends(current_user)):
    security.require_write(user)
    instance = services.create_instance(
        user, payload.name, payload.os, payload.cpu, payload.ram, payload.storage
    )
    return {"instance": instance}


@app.post("/api/instances/{instance_id}/{action}")
def control_instance(
    instance_id: int, action: str, user: dict[str, Any] = Depends(current_user)
):
    security.require_write(user)
    if action not in ("start", "stop", "restart"):
        raise AuthError("Unsupported action.")
    return {"instance": services.control_instance(user, instance_id, action)}


@app.delete("/api/instances/{instance_id}")
def delete_instance(
    instance_id: int,
    delete_data: bool = Query(default=False),
    user: dict[str, Any] = Depends(current_user),
):
    security.require_write(user)
    services.delete_instance(user, instance_id, delete_data)
    return {"ok": True}


# ===========================================================================
# Storage
# ===========================================================================

@app.get("/api/files")
def get_files(user: dict[str, Any] = Depends(current_user)):
    return {"files": services.list_files(user)}


@app.get("/api/storage/summary")
def get_storage_summary(user: dict[str, Any] = Depends(current_user)):
    return {"summary": services.storage_summary(user)}


@app.post("/api/files", status_code=201)
def upload_files(
    files: list[UploadFile] = File(...),
    user: dict[str, Any] = Depends(current_user),
):
    security.require_write(user)
    saved = []
    for upload in files:
        saved.append(
            services.save_upload(user, upload.filename, upload.file, upload.content_type)
        )
    return {"files": saved}


@app.post("/api/files/folder", status_code=201)
def create_folder(payload: FolderCreate, user: dict[str, Any] = Depends(current_user)):
    security.require_write(user)
    return {"file": services.save_folder(user, payload.name)}


@app.get("/api/files/{file_id}/download")
def download_file(file_id: int, user: dict[str, Any] = Depends(current_user)):
    row = services.get_file(user, file_id)
    return FileResponse(
        row["stored_path"],
        filename=row["name"],
        media_type=services.guess_content_type(row["name"]),
    )


@app.get("/api/files/{file_id}/view")
def view_file(file_id: int, user: dict[str, Any] = Depends(current_user)):
    row = services.get_file(user, file_id)
    return FileResponse(
        row["stored_path"],
        media_type=services.guess_content_type(row["name"]),
        content_disposition_type="inline",
    )


@app.delete("/api/files/{file_id}")
def delete_file(file_id: int, user: dict[str, Any] = Depends(current_user)):
    security.require_write(user)
    services.delete_file(user, file_id)
    return {"ok": True}


# ===========================================================================
# Databases + SQL console
# ===========================================================================

@app.get("/api/databases")
def get_databases(user: dict[str, Any] = Depends(current_user)):
    where, params = ("WHERE d.owner_id = %s", (user["id"],))
    if user["role"] == "Administrator":
        where, params = ("", ())
    rows = db.query_all(
        f"""
        SELECT d.*, u.username AS owner_name
        FROM nimbus_databases d JOIN nimbus_users u ON u.id = d.owner_id
        {where} ORDER BY d.created_at DESC
        """,
        params,
        dictionary=True,
    )
    databases = [
        {
            "id": r["id"],
            "name": r["name"],
            "type": r["db_type"],
            "host": r["host"],
            "port": r["port"],
            "status": r["status"],
            "created": r["created_at"].strftime("%b %d, %Y")
            if hasattr(r["created_at"], "strftime")
            else str(r["created_at"]),
            "owner": r.get("owner_name") or "",
        }
        for r in rows
    ]
    return {"databases": databases}


@app.post("/api/databases", status_code=201)
def create_database(payload: DatabaseCreate, user: dict[str, Any] = Depends(current_user)):
    security.require_write(user)
    name = payload.name.strip()
    if not name:
        raise AuthError("Database name is required.")
    if not services.valid_database_name(name):
        raise AuthError("Invalid database name. Use letters, digits, '.', '_' or '-'.")
    if db.query_one(
        "SELECT id FROM nimbus_databases WHERE owner_id = %s AND name = %s",
        (user["id"], name),
    ):
        raise AuthError("A database with this name already exists.")

    if payload.type.lower() in ("mysql", "mariadb"):
        schema_name, created = services.provision_database(name)
        status = "Running" if created else "Running (shared)"
    else:
        schema_name, status = config.MYSQL_DATABASE, "Running (logical)"

    row_id = db.execute(
        "INSERT INTO nimbus_databases "
        "(owner_id, name, db_type, host, port, schema_name, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            user["id"], name, payload.type, config.MYSQL_HOST,
            payload.port or config.MYSQL_PORT, schema_name, status,
        ),
    )
    services.log_activity(user, "Database Created", name)
    row = db.query_one(
        "SELECT d.*, u.username AS owner_name FROM nimbus_databases d "
        "JOIN nimbus_users u ON u.id = d.owner_id WHERE d.id = %s",
        (row_id,),
        dictionary=True,
    )
    return {
        "database": {
            "id": row["id"],
            "name": row["name"],
            "type": row["db_type"],
            "host": row["host"],
            "port": row["port"],
            "status": row["status"],
            "created": services.now_label(),
            "owner": user["username"],
        }
    }


@app.delete("/api/databases/{database_id}")
def delete_database(database_id: int, user: dict[str, Any] = Depends(current_user)):
    security.require_write(user)
    row = db.query_one(
        "SELECT * FROM nimbus_databases WHERE id = %s", (database_id,), dictionary=True
    )
    if not row:
        raise AuthError("Database not found.")
    if row["owner_id"] != user["id"] and user["role"] != "Administrator":
        raise Forbidden("You do not have access to this database.")
    db.execute("DELETE FROM nimbus_databases WHERE id = %s", (database_id,))
    services.log_activity(user, "Database Deleted", row["name"])
    return {"ok": True}


@app.post("/api/query")
def run_query(payload: QueryRequest, user: dict[str, Any] = Depends(current_user)):
    read_only = not security.can_write(user)
    if read_only and not services.is_read_only(payload.query):
        raise Forbidden("Your role only allows read-only queries.")

    services.assert_query_allowed(payload.query, user)

    schema = services.resolve_schema(user, payload.database)
    max_rows = min(payload.max_rows or config.MAX_QUERY_ROWS, config.MAX_QUERY_ROWS)
    try:
        result = services.run_query(schema, payload.query, max_rows, read_only=read_only)
    except services.SqlError:
        services.log_activity(user, "SQL Query Failed", payload.database or schema, status="Failed")
        raise
    services.log_activity(user, "SQL Query Executed", payload.database or schema, status="Success")
    return result


# ===========================================================================
# Activity + dashboard
# ===========================================================================

@app.get("/api/activity")
def get_activity(
    user: dict[str, Any] = Depends(current_user),
    limit: int = Query(default=200, ge=1, le=1000),
):
    if user["role"] == "Administrator":
        rows = db.query_all(
            "SELECT username, action, resource, status, created_at "
            "FROM nimbus_activity ORDER BY created_at DESC LIMIT %s",
            (limit,),
            dictionary=True,
        )
    else:
        rows = db.query_all(
            "SELECT username, action, resource, status, created_at "
            "FROM nimbus_activity WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
            (user["id"], limit),
            dictionary=True,
        )
    activity = [
        {
            "user": r["username"],
            "action": r["action"],
            "resource": r["resource"] or "—",
            "time": r["created_at"].strftime("%b %d, %Y, %I:%M %p")
            if hasattr(r["created_at"], "strftime")
            else str(r["created_at"]),
            "timestamp": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
            "status": r["status"],
        }
        for r in rows
    ]
    return {"activity": activity}


@app.get("/api/dashboard/summary")
def dashboard_summary(user: dict[str, Any] = Depends(current_user)):
    instances = services.list_instances(user)
    running = sum(1 for i in instances if i["status"] == "Running")

    where, params = ("WHERE owner_id = %s", (user["id"],))
    if user["role"] == "Administrator":
        where, params = ("", ())
    db_row = db.query_one(
        f"SELECT COUNT(*) AS total FROM nimbus_databases {where}", params, dictionary=True
    )

    if user["role"] == "Administrator":
        recent = db.query_all(
            "SELECT username, action, resource, created_at FROM nimbus_activity "
            "ORDER BY created_at DESC LIMIT 6",
            dictionary=True,
        )
    else:
        recent = db.query_all(
            "SELECT username, action, resource, created_at FROM nimbus_activity "
            "WHERE user_id = %s ORDER BY created_at DESC LIMIT 6",
            (user["id"],),
            dictionary=True,
        )

    return {
        "totalInstances": len(instances),
        "runningInstances": running,
        "activeDatabases": int(db_row["total"]) if db_row else 0,
        "storage": services.storage_summary(user),
        "recent": [
            {
                "action": r["action"],
                "resource": r["resource"] or "",
                "user": r["username"],
                "time": r["created_at"].strftime("%b %d, %I:%M %p")
                if hasattr(r["created_at"], "strftime")
                else str(r["created_at"]),
            }
            for r in recent
        ],
    }


# ===========================================================================
# Profile / settings
# ===========================================================================

@app.get("/api/profile")
def get_profile(user: dict[str, Any] = Depends(current_user)):
    return {"profile": security.public_user(user)}


@app.put("/api/profile")
def update_profile(payload: ProfileUpdate, user: dict[str, Any] = Depends(current_user)):
    name = (payload.name or user["name"]).strip()
    email = (payload.email or user["email"]).strip().lower()
    notify = user.get("notify_enabled", 1)
    if payload.notifyEnabled is not None:
        notify = 1 if payload.notifyEnabled else 0

    if not name:
        raise AuthError("Name is required.")
    security.validate_email(email)

    clash = db.query_one(
        "SELECT id FROM nimbus_users WHERE email = %s AND id <> %s", (email, user["id"])
    )
    if clash:
        raise AuthError("That email is already in use.")

    db.execute(
        "UPDATE nimbus_users SET name = %s, email = %s, notify_enabled = %s WHERE id = %s",
        (name, email, notify, user["id"]),
    )
    services.log_activity(user, "Profile Updated", user["username"])
    return {"profile": security.public_user(security.get_user_by_id(user["id"]))}


@app.post("/api/profile/password")
def change_password(payload: PasswordChange, request: Request, user: dict[str, Any] = Depends(current_user)):
    record = security.get_user_by_identifier(user["username"])
    if not security.verify_password(payload.current, record["password_hash"]):
        raise AuthError("Your current password is incorrect.")
    security.validate_password(payload.new)
    if payload.new == payload.current:
        raise AuthError("New password must be different from the current password.")
    db.execute(
        "UPDATE nimbus_users SET password_hash = %s WHERE id = %s",
        (security.hash_password(payload.new), user["id"]),
    )
    # Revoke every other session, then re-issue one for the caller so they stay
    # signed in on this device.
    security.destroy_user_sessions(user["id"])
    token = security.create_session(user["id"])
    services.log_activity(user, "Password Changed", user["username"])
    response = JSONResponse(content={"ok": True})
    _set_session_cookie(response, token)
    return response


# ===========================================================================
# Health
# ===========================================================================

@app.get("/api/health")
def health():
    ok, info = db.ping()
    return {
        "database": {"ok": ok, "info": info},
        "docker": services.docker_available(),
        "storage": str(config.STORAGE_DIR),
    }


# ===========================================================================
# Docker terminal (WebSocket bridge)
# ===========================================================================

@app.get("/api/containers")
def get_containers(user: dict[str, Any] = Depends(current_user)):
    return {"containers": services.list_running_containers(user)}


def _socket_send(sock, data: bytes) -> None:
    # docker-py hands back a read-only SocketIO wrapper; the underlying socket
    # is full-duplex, so write through it directly.
    inner = getattr(sock, "_sock", None)
    if inner is not None and hasattr(inner, "sendall"):
        inner.sendall(data)
    elif hasattr(sock, "sendall"):
        sock.sendall(data)
    elif hasattr(sock, "write"):
        sock.write(data)
    else:  # pragma: no cover
        raise RuntimeError("No writable handle on docker exec socket.")


def _socket_recv(sock, size: int = 4096) -> bytes:
    if hasattr(sock, "recv"):
        return sock.recv(size)
    return sock.read(size)


@app.websocket("/api/containers/{container_id}/terminal")
async def container_terminal(websocket: WebSocket, container_id: str):
    token = websocket.cookies.get(config.SESSION_COOKIE)
    user = await run_in_threadpool(security.user_from_token, token)
    if not user:
        await websocket.close(code=4401)
        return

    try:
        client, container = await run_in_threadpool(
            services.authorize_container, user, container_id
        )
    except Exception:  # noqa: BLE001
        await websocket.close(code=4403)
        return

    await websocket.accept()
    await websocket.send_text(f"Connected to {container.name}\r\n")

    try:
        exec_id = await run_in_threadpool(
            client.api.exec_create,
            container.id,
            ["/bin/sh"],
            stdout=True,
            stderr=True,
            stdin=True,
            tty=True,
        )
        sock = await run_in_threadpool(
            client.api.exec_start, exec_id["Id"], tty=True, socket=True
        )
    except Exception as exc:  # noqa: BLE001
        await websocket.send_text(f"\r\n[Could not start shell: {exc}]\r\n")
        await websocket.close()
        return

    loop = asyncio.get_running_loop()
    stop = threading.Event()

    def reader() -> None:
        try:
            while not stop.is_set():
                data = _socket_recv(sock)
                if not data:
                    break
                asyncio.run_coroutine_threadsafe(
                    websocket.send_text(data.decode("utf-8", "replace")), loop
                )
        except Exception:  # noqa: BLE001
            pass
        finally:
            asyncio.run_coroutine_threadsafe(websocket.close(), loop)

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    try:
        while True:
            message = await websocket.receive_text()
            await run_in_threadpool(_socket_send, sock, (message + "\n").encode())
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        stop.set()
        try:
            sock.close()
        except Exception:  # noqa: BLE001
            pass


# ===========================================================================
# Static frontend (registered last so /api/* wins)
# ===========================================================================

app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
