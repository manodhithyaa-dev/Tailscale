"""Nimbus Console backend: serves the frontend and a JSON API on one origin.

Run:  python app.py        ->  http://127.0.0.1:5000
"""
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, g, jsonify, request, send_file, send_from_directory, session
from flask_sock import Sock
from werkzeug.security import check_password_hash, generate_password_hash

import db
import docker_manager as dm
import sql_runner

BASE = Path(__file__).resolve().parent
FRONTEND = (BASE.parent / "frontend").resolve()
ADMIN, DEV, VIEWER = "Administrator", "Developer", "Viewer"
WRITERS = (ADMIN, DEV)
USER_QUOTA = 1024 * 1024 * 1024        # 1 GB of file storage per user
TERMINAL_IDLE = 15 * 60

db.init_db()
app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=db.get_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("NIMBUS_HTTPS")),
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=200 * 1024 * 1024,
)
sock = Sock(app)
app.teardown_appcontext(db.close_db)


# ------------------------------------------------------------------ helpers
def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fail(msg, code=400):
    return jsonify(error=msg), code


def body():
    return request.get_json(silent=True) or {}


def current_user():
    if "u" not in g:
        uid = session.get("uid")
        g.u = db.q1("SELECT * FROM users WHERE id=?", (uid,)) if uid else None
    return g.u


def auth(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **k):
            u = current_user()
            if not u:
                return fail("Not signed in.", 401)
            if roles and u["role"] not in roles:
                return fail("Your role does not allow this action.", 403)
            return fn(*a, **k)
        return wrapper
    return deco


def log(action, resource="", status="Success", user=None):
    u = user or current_user()
    db.execute("INSERT INTO activity(user_id,username,action,resource,status,created_at) VALUES(?,?,?,?,?,?)",
               (u["id"] if u else None, u["username"] if u else "anonymous", action, resource, status, now()))


def is_admin(u):
    return u["role"] == ADMIN


def public_user(u):
    return {"id": u["id"], "name": u["full_name"], "username": u["username"], "email": u["email"], "role": u["role"]}


@app.before_request
def csrf_guard():
    # Cross-site pages cannot set custom headers, so this blocks CSRF on every state-changing call.
    if request.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("X-Requested-With") != "nimbus":
            return fail("Missing X-Requested-With header.", 403)


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if not request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.errorhandler(413)
def too_big(_e):
    return fail("Upload too large (200 MB limit).", 413)


@app.errorhandler(500)
def server_error(_e):
    return fail("Internal server error - check the server console.", 500)


# ------------------------------------------------------------------ auth
_fails = {}


def throttled(key):
    t = time.time()
    _fails[key] = [x for x in _fails.get(key, []) if t - x < 300]
    return len(_fails[key]) >= 5


@app.post("/api/signup")
def signup():
    b = body()
    name = str(b.get("name", "")).strip()
    username = str(b.get("username", "")).strip()
    email = str(b.get("email", "")).strip()
    password = str(b.get("password", ""))
    if not (1 <= len(name) <= 80):
        return fail("Enter your full name.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
        return fail("Username: 3-32 characters, letters, digits, . _ -")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 120:
        return fail("Enter a valid email address.")
    if len(password) < 8:
        return fail("Password must be at least 8 characters.")
    first = db.q1("SELECT COUNT(*) AS n FROM users")["n"] == 0
    role, notice = b.get("role"), ""
    if first:
        role = ADMIN                      # first account bootstraps the platform
    elif role not in (DEV, VIEWER):
        role, notice = DEV, "Administrator accounts are granted by an existing admin; you were registered as Developer."
    try:
        uid = db.execute(
            "INSERT INTO users(username,email,full_name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)",
            (username, email, name, generate_password_hash(password), role, now()))
    except sqlite3.IntegrityError:
        return fail("That username or email is already registered.", 409)
    session.clear()
    session["uid"] = uid
    session.permanent = True
    g.pop("u", None)
    log("Account Created", username)
    return jsonify(user=public_user(current_user()), notice=notice)


@app.post("/api/login")
def login():
    b = body()
    ident = str(b.get("user", "")).strip()
    key = f"{request.remote_addr}|{ident.lower()}"
    if throttled(key):
        return fail("Too many failed attempts. Try again in a few minutes.", 429)
    u = db.q1("SELECT * FROM users WHERE username=? OR email=?", (ident, ident))
    if not u or not check_password_hash(u["password_hash"], str(b.get("password", ""))):
        _fails.setdefault(key, []).append(time.time())
        log("Login", ident[:60], "Failed", user={"id": None, "username": "anonymous"})
        return fail("Invalid username or password.", 401)
    _fails.pop(key, None)
    session.clear()
    session["uid"] = u["id"]
    session.permanent = True
    log("Login", u["username"], user=u)
    return jsonify(user=public_user(u))


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
@auth()
def me():
    return jsonify(user=public_user(current_user()))


@app.post("/api/me")
@auth()
def update_me():
    u, b = current_user(), body()
    name, email = str(b.get("name", "")).strip(), str(b.get("email", "")).strip()
    if not (1 <= len(name) <= 80) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return fail("Enter a valid name and email.")
    try:
        db.execute("UPDATE users SET full_name=?, email=? WHERE id=?", (name, email, u["id"]))
    except sqlite3.IntegrityError:
        return fail("That email is already in use.", 409)
    g.pop("u", None)
    log("Profile Updated", u["username"])
    return jsonify(user=public_user(current_user()))


# ------------------------------------------------------------------ health / dashboard
_ts = {"t": 0, "v": None}


def tailscale_status():
    if _ts["v"] and time.time() - _ts["t"] < 15:
        return _ts["v"]
    exe, v = shutil.which("tailscale"), {"installed": False, "connected": False, "ip": None}
    v["installed"] = bool(exe)
    if exe:
        try:
            out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=3)
            lines = out.stdout.split()
            if out.returncode == 0 and lines:
                v.update(connected=True, ip=lines[0])
        except Exception:
            pass
    _ts.update(t=time.time(), v=v)
    return v


def live_status():
    try:
        return dm.statuses(), True
    except dm.DockerError:
        return {}, False


def instance_rows(u):
    sql = "SELECT i.*, u.username FROM instances i JOIN users u ON u.id=i.owner_id"
    if u["role"] in (ADMIN, VIEWER):
        return db.q(sql + " ORDER BY i.id DESC")
    return db.q(sql + " WHERE i.owner_id=? ORDER BY i.id DESC", (u["id"],))


def get_instance(u, iid):
    r = db.q1("SELECT i.*, u.username FROM instances i JOIN users u ON u.id=i.owner_id WHERE i.instance_id=?", (iid,))
    if r and (u["role"] in (ADMIN, VIEWER) or r["owner_id"] == u["id"]):
        return r
    return None


def can_manage(u, r):
    return u["role"] == ADMIN or (u["role"] == DEV and r["owner_id"] == u["id"])


@app.get("/api/health")
@auth()
def health():
    return jsonify(tailscale=tailscale_status(), docker=live_status()[1])


@app.get("/api/dashboard")
@auth()
def dashboard():
    u = current_user()
    rows = instance_rows(u)
    live, docker_ok = live_status()
    running = sum(1 for r in rows if live.get(r["container_name"], {}).get("status") == "running")
    scope, args = ("", ()) if is_admin(u) else (" WHERE owner_id=?", (u["id"],))
    used = db.q1("SELECT COALESCE(SUM(size),0) AS n FROM files" + scope, args)["n"]
    dbs = db.q1("SELECT COUNT(*) AS n FROM databases" + scope, args)["n"]
    recent = db.q("SELECT username,action,resource,status,created_at FROM activity" + scope + " ORDER BY id DESC LIMIT 4", args)
    return jsonify(total_instances=len(rows), running_instances=running, storage_bytes=used, databases=dbs,
                   recent=recent, docker=docker_ok, tailscale=tailscale_status())


# ------------------------------------------------------------------ instances
def inst_json(r, live, docker_ok, u):
    l = live.get(r["container_name"])
    status = l["status"].capitalize() if l else ("Missing" if docker_ok else "Unknown")
    return {"id": r["instance_id"], "name": r["name"], "os": dm.OS_LABELS.get(r["os"], r["os"]),
            "status": status, "ip": l["ip"] if l else "", "cpu": r["cpu"],
            "ram_gb": round(r["ram_mb"] / 1024, 2), "storage_gb": r["storage_gb"],
            "created": r["created_at"], "owner": r["username"], "can_manage": can_manage(u, r)}


@app.get("/api/instances")
@auth()
def list_instances():
    u = current_user()
    live, docker_ok = live_status()
    return jsonify(docker=docker_ok, instances=[inst_json(r, live, docker_ok, u) for r in instance_rows(u)])


@app.post("/api/instances")
@auth(*WRITERS)
def create_instance():
    u, b = current_user(), body()
    name, os_key = str(b.get("name", "")).strip(), b.get("os")
    try:
        cpu, ram_mb, storage = float(b.get("cpu", 1)), int(float(b.get("ram_gb", 1)) * 1024), int(b.get("storage_gb", 10))
    except (TypeError, ValueError):
        return fail("CPU, RAM and storage must be numbers.")
    if db.q1("SELECT 1 FROM instances WHERE owner_id=? AND name=?", (u["id"], name)):
        return fail("You already have an instance with this name.", 409)
    container = f"{name}-{secrets.token_hex(3)}"
    try:
        dm.validate_resources(cpu, ram_mb, storage)
        dm.create_instance(container, os_key, cpu, ram_mb, storage)
    except dm.DockerError as exc:
        log("Instance Create", name, "Failed")
        return fail(str(exc), 400 if "Docker is not" not in str(exc) else 503)
    iid = "i-" + secrets.token_hex(3)
    try:
        db.execute("INSERT INTO instances(instance_id,owner_id,name,container_name,os,cpu,ram_mb,storage_gb,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (iid, u["id"], name, container, os_key, cpu, ram_mb, storage, now()))
    except sqlite3.Error:
        dm.remove(container, True)
        return fail("Could not record the instance.", 500)
    log("Instance Created", name)
    return jsonify(id=iid), 201


@app.post("/api/instances/<iid>/action")
@auth(*WRITERS)
def instance_action(iid):
    u, action = current_user(), body().get("action")
    r = get_instance(u, iid)
    if not r or not can_manage(u, r):
        return fail("Instance not found.", 404)
    try:
        dm.control(r["container_name"], action)
    except dm.DockerError as exc:
        log(f"Instance {str(action).capitalize()}", r["name"], "Failed")
        return fail(str(exc), 400)
    log({"start": "Instance Started", "stop": "Instance Stopped", "restart": "Instance Restarted"}[action], r["name"])
    return jsonify(ok=True)


@app.delete("/api/instances/<iid>")
@auth(*WRITERS)
def delete_instance(iid):
    u = current_user()
    r = get_instance(u, iid)
    if not r or not can_manage(u, r):
        return fail("Instance not found.", 404)
    try:
        dm.remove(r["container_name"], delete_data=True)
    except dm.DockerError as exc:
        log("Instance Deleted", r["name"], "Failed")
        return fail(str(exc), 400)
    db.execute("DELETE FROM instances WHERE id=?", (r["id"],))
    log("Instance Deleted", r["name"])
    return jsonify(ok=True)


# ------------------------------------------------------------------ terminal (docker exec over WebSocket)
@app.get("/api/containers")
@auth(*WRITERS)
def containers():
    u = current_user()
    rows = instance_rows(u) if is_admin(u) else [r for r in instance_rows(u) if r["owner_id"] == u["id"]]
    live, _ = live_status()
    return jsonify(containers=[{"id": r["instance_id"], "name": r["name"],
                                "status": live.get(r["container_name"], {}).get("status", "unknown")} for r in rows])


@sock.route("/api/containers/<iid>/terminal")
def terminal(ws, iid):
    u = current_user()
    origin = request.headers.get("Origin")
    if not u or u["role"] not in WRITERS or (origin and urlparse(origin).netloc != request.host):
        ws.send("[Unauthorized]\r\n")
        ws.close()
        return
    r = get_instance(u, iid)
    if not r or not can_manage(u, r):
        ws.send("[Instance not found]\r\n")
        ws.close()
        return
    try:
        shell = dm.Shell(r["container_name"])
    except dm.DockerError as exc:
        ws.send(f"[{exc}]\r\n")
        ws.close()
        return
    log("Terminal Session", r["name"], user=u)
    stop = threading.Event()

    def pump():
        try:
            while not stop.is_set():
                data = shell.recv()
                if not data:
                    break
                ws.send(data.decode("utf-8", "replace"))
        except Exception:
            pass
        finally:
            stop.set()
            try:
                ws.close()
            except Exception:
                pass

    threading.Thread(target=pump, daemon=True).start()
    last = time.time()
    try:
        while not stop.is_set():
            msg = ws.receive(timeout=1)
            if msg is None:
                if time.time() - last > TERMINAL_IDLE:
                    ws.send("\r\n[Session closed: idle timeout]\r\n")
                    break
                continue
            last = time.time()
            shell.send(msg.encode() if isinstance(msg, str) else msg)
    except Exception:
        pass
    finally:
        stop.set()
        shell.close()


# ------------------------------------------------------------------ files
def file_type(name):
    mt = (mimetypes.guess_type(name)[0] or "")
    if mt.startswith("image/"):
        return "Image"
    if mt == "application/pdf":
        return "PDF"
    if mt.startswith("text/") or name.lower().endswith((".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".md", ".csv")):
        return "Document"
    return "Other"


def file_rows(u):
    sql = "SELECT f.*, u.username FROM files f JOIN users u ON u.id=f.owner_id"
    if is_admin(u):
        return db.q(sql + " ORDER BY f.id DESC")
    return db.q(sql + " WHERE f.owner_id=? ORDER BY f.id DESC", (u["id"],))


def get_file(u, fid):
    r = db.q1("SELECT * FROM files WHERE id=?", (fid,))
    return r if r and (is_admin(u) or r["owner_id"] == u["id"]) else None


@app.get("/api/files")
@auth()
def list_files():
    u = current_user()
    return jsonify(files=[{"id": r["id"], "name": r["name"], "type": r["type"], "size": r["size"], "created": r["created_at"],
                           "owner": r["username"], "folder": bool(r["is_folder"])} for r in file_rows(u)])


@app.post("/api/files")
@auth(*WRITERS)
def upload_files():
    u = current_user()
    uploads = request.files.getlist("files")
    if not uploads:
        return fail("No files received.")
    used = db.q1("SELECT COALESCE(SUM(size),0) AS n FROM files WHERE owner_id=?", (u["id"],))["n"]
    folder = db.STORAGE_DIR / str(u["id"])
    folder.mkdir(exist_ok=True)
    saved = 0
    for f in uploads:
        name = re.sub(r"[\x00-\x1f/\\]", "", os.path.basename(f.filename or "file"))[:200] or "file"
        stored = uuid.uuid4().hex
        path = folder / stored
        f.save(path)
        size = path.stat().st_size
        if used + size > USER_QUOTA:
            path.unlink(missing_ok=True)
            return fail("Storage quota (1 GB) exceeded.", 413)
        used += size
        db.execute("INSERT INTO files(owner_id,name,stored_name,type,size,created_at) VALUES(?,?,?,?,?,?)",
                   (u["id"], name, stored, file_type(name), size, now()))
        log("File Uploaded", name)
        saved += 1
    return jsonify(uploaded=saved), 201


@app.post("/api/folders")
@auth(*WRITERS)
def create_folder():
    u, name = current_user(), str(body().get("name", "")).strip()[:100]
    if not name or re.search(r"[\x00-\x1f/\\]", name):
        return fail("Enter a valid folder name.")
    db.execute("INSERT INTO files(owner_id,name,type,size,is_folder,created_at) VALUES(?,?,?,?,1,?)",
               (u["id"], name, "Folder", 0, now()))
    log("Folder Created", name)
    return jsonify(ok=True), 201


@app.get("/api/files/<int:fid>/download")
@auth()
def download_file(fid):
    u = current_user()
    r = get_file(u, fid)
    if not r or r["is_folder"]:
        return fail("File not found.", 404)
    path = db.STORAGE_DIR / str(r["owner_id"]) / r["stored_name"]
    if not path.exists():
        return fail("File data is missing on disk.", 404)
    mt = mimetypes.guess_type(r["name"])[0] or "application/octet-stream"
    inline = request.args.get("inline") == "1" and mt in ("image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain")
    log("File Downloaded" if not inline else "File Viewed", r["name"])
    return send_file(path, mimetype=mt if inline else "application/octet-stream", as_attachment=not inline, download_name=r["name"])


@app.delete("/api/files/<int:fid>")
@auth(*WRITERS)
def delete_file(fid):
    u = current_user()
    r = get_file(u, fid)
    if not r:
        return fail("File not found.", 404)
    if r["stored_name"]:
        (db.STORAGE_DIR / str(r["owner_id"]) / r["stored_name"]).unlink(missing_ok=True)
    db.execute("DELETE FROM files WHERE id=?", (fid,))
    log("File Deleted", r["name"])
    return jsonify(ok=True)


# ------------------------------------------------------------------ databases + SQL
def db_rows(u):
    sql = "SELECT d.*, u.username FROM databases d JOIN users u ON u.id=d.owner_id"
    if is_admin(u):
        return db.q(sql + " ORDER BY d.id DESC")
    return db.q(sql + " WHERE d.owner_id=? ORDER BY d.id DESC", (u["id"],))


def get_database(u, ident, by_id=False):
    if by_id:
        r = db.q1("SELECT * FROM databases WHERE id=?", (ident,))
        return r if r and (is_admin(u) or r["owner_id"] == u["id"]) else None
    r = db.q1("SELECT * FROM databases WHERE name=? AND owner_id=?", (ident, u["id"]))
    if not r and is_admin(u):
        r = db.q1("SELECT * FROM databases WHERE name=? ORDER BY id LIMIT 1", (ident,))
    return r


@app.get("/api/databases")
@auth()
def list_databases():
    u = current_user()
    return jsonify(databases=[{
        "id": r["id"], "name": r["name"], "engine": r["engine"],
        "type": "SQLite (managed)" if r["engine"] == "sqlite" else "MySQL",
        "host": "local" if r["engine"] == "sqlite" else r["host"],
        "port": r["port"] if r["engine"] == "mysql" else None,
        "created": r["created_at"], "owner": r["username"], "can_manage": u["role"] in WRITERS} for r in db_rows(u)])


@app.post("/api/databases")
@auth(*WRITERS)
def create_database():
    u, b = current_user(), body()
    name, engine = str(b.get("name", "")).strip(), b.get("engine")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", name):
        return fail("Name: letters, digits, . _ - (max 63 chars).")
    if engine not in ("sqlite", "mysql"):
        return fail("Engine must be SQLite or MySQL.")
    if db.q1("SELECT 1 FROM databases WHERE owner_id=? AND name=?", (u["id"], name)):
        return fail("You already have a database with this name.", 409)
    if engine == "sqlite":
        path = db.USERDB_DIR / f"{uuid.uuid4().hex}.db"
        sql_runner.create_sqlite(path)
        db.execute("INSERT INTO databases(owner_id,name,engine,path,created_at) VALUES(?,?,?,?,?)",
                   (u["id"], name, "sqlite", str(path), now()))
    else:
        host, user, pw, dbname = (str(b.get(k, "")).strip() for k in ("host", "username", "password", "dbname"))
        try:
            port = int(b.get("port") or 3306)
        except ValueError:
            return fail("Port must be a number.")
        if not (host and user and pw and dbname) or not (1 <= port <= 65535):
            return fail("MySQL needs host, port, username, password and database name.")
        cfg = {"host": host, "port": port, "db_username": user, "db_password_enc": db.encrypt(pw), "db_name": dbname}
        try:
            sql_runner.test_mysql(cfg)
        except sql_runner.QueryError as exc:
            log("Database Create", name, "Failed")
            return fail(str(exc))
        db.execute("INSERT INTO databases(owner_id,name,engine,host,port,db_username,db_password_enc,db_name,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (u["id"], name, "mysql", host, port, user, cfg["db_password_enc"], dbname, now()))
    log("Database Created", name)
    return jsonify(ok=True), 201


@app.delete("/api/databases/<int:did>")
@auth(*WRITERS)
def delete_database(did):
    u = current_user()
    r = get_database(u, did, by_id=True)
    if not r:
        return fail("Database not found.", 404)
    if r["engine"] == "sqlite" and r["path"]:
        for suffix in ("", "-wal", "-shm"):
            Path(r["path"] + suffix).unlink(missing_ok=True)
    db.execute("DELETE FROM databases WHERE id=?", (did,))
    log("Database Deleted", r["name"])
    return jsonify(ok=True)


@app.get("/api/databases/<int:did>/tables")
@auth(*WRITERS)
def database_tables(did):
    r = get_database(current_user(), did, by_id=True)
    if not r:
        return fail("Database not found.", 404)
    try:
        return jsonify(tables=sql_runner.tables_sqlite(r["path"]) if r["engine"] == "sqlite" else sql_runner.tables_mysql(r))
    except (sql_runner.QueryError, sqlite3.Error) as exc:
        return fail(str(exc))


@app.post("/api/query")
@auth(*WRITERS)
def run_query():
    u, b = current_user(), body()
    query = str(b.get("query", "")).strip()
    if not query:
        return fail("Enter a query before running it.")
    if len(query) > 20000:
        return fail("Query too long.")
    if b.get("database_id") not in (None, ""):
        r = get_database(u, b.get("database_id"), by_id=True)
    else:
        r = get_database(u, str(b.get("database", "")).strip())
    if not r:
        return fail("Database not found. Create one on the Database page first.", 404)
    try:
        result = (sql_runner.run_sqlite(r["path"], query) if r["engine"] == "sqlite" else sql_runner.run_mysql(r, query))
    except sql_runner.QueryError as exc:
        log("SQL Query Executed", r["name"], "Failed")
        return fail(str(exc))
    log("SQL Query Executed", r["name"])
    return jsonify(result)


# ------------------------------------------------------------------ activity
@app.get("/api/activity")
@auth()
def activity():
    u = current_user()
    limit = min(int(request.args.get("limit", 200) or 200), 500)
    if is_admin(u):
        rows = db.q("SELECT username,action,resource,status,created_at FROM activity ORDER BY id DESC LIMIT ?", (limit,))
    else:
        rows = db.q("SELECT username,action,resource,status,created_at FROM activity WHERE user_id=? ORDER BY id DESC LIMIT ?", (u["id"], limit))
    return jsonify(activity=rows)


# ------------------------------------------------------------------ frontend
ALLOWED_STATIC = {".html", ".css", ".js", ".svg", ".png", ".ico", ".jpg", ".webp"}


@app.get("/")
def index():
    return send_from_directory(FRONTEND, "login.html")


@app.get("/<path:p>")
def static_files(p):
    if p.startswith("api/") or Path(p).suffix.lower() not in ALLOWED_STATIC:
        return fail("Not found.", 404)
    return send_from_directory(FRONTEND, p)


if __name__ == "__main__":
    host = os.environ.get("NIMBUS_HOST", "127.0.0.1")
    port = int(os.environ.get("NIMBUS_PORT", "5000"))
    print(f"\n  Nimbus Console -> http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}\n")
    app.run(host=host, port=port, threaded=True)
