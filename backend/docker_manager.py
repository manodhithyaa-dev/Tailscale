"""Docker logic shared by the web API (app.py) and the CLI (cloud_instances.py)."""
import re

import docker
from docker.errors import APIError, ImageNotFound, NotFound

IMAGES = {
    "ubuntu": "ubuntu:latest",
    "debian": "debian:latest",
    "alpine": "alpine:latest",
    "amazonlinux": "amazonlinux:latest",
}
OS_LABELS = {"ubuntu": "Ubuntu", "debian": "Debian", "alpine": "Alpine", "amazonlinux": "Amazon Linux"}
LABEL = "cloud.instance"


class DockerError(Exception):
    pass


_client = None


def client():
    global _client
    try:
        if _client is None:
            _client = docker.from_env()
        _client.ping()
        return _client
    except Exception as exc:
        _client = None
        raise DockerError(f"Docker is not reachable - is Docker running? ({exc})")


def valid_name(name):
    return bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", name or ""))


def validate_resources(cpu, ram_mb, storage_gb):
    if not (1 <= cpu <= 4):
        raise DockerError("CPU must be between 1 and 4 cores.")
    if not (256 <= ram_mb <= 8192):
        raise DockerError("RAM must be between 256 MB and 8192 MB.")
    if not (1 <= storage_gb <= 100):
        raise DockerError("Storage must be between 1 and 100 GB.")


def _get(name):
    try:
        return client().containers.get(name)
    except NotFound:
        raise DockerError(f"Container '{name}' no longer exists in Docker.")
    except APIError as exc:
        raise DockerError(str(exc))


def create_instance(name, os_key, cpu, ram_mb, storage_gb):
    """Create + start a container with CPU/RAM limits and a persistent /data volume."""
    if not valid_name(name):
        raise DockerError("Invalid instance name.")
    if os_key not in IMAGES:
        raise DockerError(f"Supported OS: {', '.join(IMAGES)}")
    validate_resources(cpu, ram_mb, storage_gb)
    c = client()
    try:
        c.containers.get(name)
        raise DockerError("A container with this name already exists.")
    except NotFound:
        pass
    image = IMAGES[os_key]
    try:
        c.images.get(image)
    except ImageNotFound:
        try:
            c.images.pull(image)
        except APIError as exc:
            raise DockerError(f"Could not pull image {image}: {exc}")
    volume = c.volumes.create(name=f"{name}-data")
    try:
        ct = c.containers.run(
            image=image, name=name,
            command=["sh", "-c", "while true; do sleep 3600; done"],
            detach=True, tty=True, stdin_open=True,
            nano_cpus=int(cpu * 1_000_000_000), mem_limit=f"{ram_mb}m",
            volumes={volume.name: {"bind": "/data", "mode": "rw"}},
            labels={LABEL: "true", "cloud.os": os_key, "cloud.storage_gb": str(storage_gb)},
            restart_policy={"Name": "unless-stopped"},
        )
    except Exception as exc:
        try:
            volume.remove(force=True)
        except APIError:
            pass
        raise DockerError(f"Creation failed: {exc}")
    return {"id": ct.short_id, "status": ct.status, "volume": volume.name}


def control(name, action):
    ct = _get(name)
    try:
        if action == "start":
            ct.start()
        elif action == "stop":
            ct.stop(timeout=10)
        elif action == "restart":
            ct.restart(timeout=10)
        else:
            raise DockerError("Unknown action.")
    except APIError as exc:
        raise DockerError(str(exc))


def remove(name, delete_data=False):
    c = client()
    try:
        c.containers.get(name).remove(force=True)
    except NotFound:
        pass
    except APIError as exc:
        raise DockerError(str(exc))
    if delete_data:
        try:
            c.volumes.get(f"{name}-data").remove(force=True)
        except (NotFound, APIError):
            pass


def statuses():
    """{container_name: {status, ip}} for all containers created by this platform."""
    out = {}
    for ct in client().containers.list(all=True, filters={"label": f"{LABEL}=true"}):
        ip = ""
        try:
            nets = ct.attrs["NetworkSettings"]["Networks"]
            ip = next((n["IPAddress"] for n in nets.values() if n.get("IPAddress")), "")
        except Exception:
            pass
        out[ct.name] = {"status": ct.status, "ip": ip, "image": ct.image.tags[0] if ct.image.tags else "unknown", "short_id": ct.short_id}
    return out


class Shell:
    """Interactive shell inside a container (docker exec with a TTY)."""

    def __init__(self, name):
        ct = _get(name)
        if ct.status != "running":
            raise DockerError("Instance is not running. Start it first.")
        api = client().api
        ex = api.exec_create(
            ct.id, ["/bin/sh", "-c", "command -v bash >/dev/null 2>&1 && exec bash || exec sh"],
            stdin=True, tty=True, environment={"TERM": "dumb"})
        self._stream = api.exec_start(ex["Id"], socket=True, tty=True)
        self._sock = getattr(self._stream, "_sock", self._stream)

    def recv(self):
        return self._sock.recv(4096)

    def send(self, data: bytes):
        self._sock.sendall(data)

    def close(self):
        try:
            self._sock.sendall(b"\x04exit\n")
        except Exception:
            pass
        try:
            self._stream.close()
        except Exception:
            pass
