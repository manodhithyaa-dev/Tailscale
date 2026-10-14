# Nimbus Console

A private cloud management console for a Tailscale-connected environment. The web
frontend (static HTML/CSS/JS) is served by a single **FastAPI** backend that ties
together real Docker containers, a real MySQL server, and per-user file storage,
behind cookie-based user authentication and role-based access control.

## Features

- **Authentication** — signup / login / logout with server-side sessions
  (opaque token in an `HttpOnly` cookie), passwords hashed with Werkzeug.
- **Roles** — `Administrator`, `Developer`, `Viewer`. Viewers are read-only,
  Developers can manage resources, Administrators can see all users' resources.
- **Per-user isolation** — instances, files, databases and activity are scoped to
  the owner; admins see everything.
- **Compute** — create / start / stop / restart / delete real Docker containers
  (`ubuntu`, `debian`, `amazonlinux`, `alpine`) with CPU / RAM limits and a
  persistent data volume.
- **Terminal** — interactive WebSocket shell into a running container.
- **Storage** — upload files, create folders, download, view and delete, with a
  per-user quota.
- **Databases** — provision per-user MySQL databases with a graceful fallback and
  a SQL query console (`/api/query`) protected against writes for viewers.
- **Activity log** — every action is recorded and displayed per-user (or globally
  for admins).
- **Dashboard** — live summary of instances, storage and databases.

## Stack

- Backend: FastAPI + Uvicorn, `mysql-connector-python`, `docker` (docker-py)
- Database: MySQL 8 (`cloud_db`)
- Frontend: static HTML/CSS/JS (no build step)

## Requirements

- Python 3.10+
- A running MySQL 8 server with a user that can create tables in `cloud_db`
- A running Docker daemon
- The user running the console must be able to access the Docker socket and the
  MySQL server

## Setup

```bash
# 1. Virtualenv + dependencies
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 2. Configure (optional — sensible defaults are built in)
cp backend/.env.example backend/.env
# edit backend/.env with your MySQL host/user/password and SECRET_KEY
```

Configuration keys (see `backend/.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `NIMBUS_DB_HOST` / `NIMBUS_DB_PORT` | `127.0.0.1` / `3306` | MySQL server |
| `NIMBUS_DB_USER` / `NIMBUS_DB_PASSWORD` | `clouduser` / `your_password` | MySQL credentials |
| `NIMBUS_DB_NAME` | `cloud_db` | Database name |
| `NIMBUS_SECRET_KEY` | dev value | Session token signing |
| `NIMBUS_QUOTA_GB` | `100` | Per-user storage quota |
| `NIMBUS_MAX_UPLOAD_MB` | `200` | Max single upload size |
| `NIMBUS_HOST` / `NIMBUS_PORT` | `127.0.0.1` / `8000` | Bind address |

> On an empty users table the console seeds a default administrator:
> **`admin` / `admin123`**. Change this password immediately after first login.

## Run

```bash
./venv/bin/uvicorn console_server:app --host 0.0.0.0 --port 8000
```

Run from the `backend/` directory (or pass `--app-dir backend`). The frontend is
mounted at `/`.

### systemd

```bash
sudo cp systemd/nimbus-console.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nimbus-console.service
```

Edit the `User`, `WorkingDirectory` and `ExecStart` paths in the unit to match
your installation.

## API overview

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/auth/signup` | Create account |
| `POST` | `/api/auth/login` | Start session |
| `POST` | `/api/auth/logout` | End session |
| `GET` | `/api/auth/me` | Current user |
| `GET`/`POST` | `/api/instances` | List / create compute instances |
| `POST` | `/api/instances/{id}/{start,stop,restart}` | Control an instance |
| `DELETE` | `/api/instances/{id}` | Delete (with `?delete_data=`) |
| `GET`/`POST` | `/api/files` | List / upload files |
| `POST` | `/api/files/folder` | Create folder |
| `GET` | `/api/files/{id}/download` | Download a file |
| `GET` | `/api/files/{id}/view` | View file contents |
| `DELETE` | `/api/files/{id}` | Delete a file |
| `GET` | `/api/storage/summary` | Storage usage |
| `GET`/`POST` | `/api/databases` | List / provision databases |
| `DELETE` | `/api/databases/{name}` | Drop a database |
| `POST` | `/api/query` | Run SQL (read-only for viewers) |
| `GET` | `/api/activity` | Activity log |
| `GET` | `/api/dashboard/summary` | Dashboard stats |
| `GET`/`PUT` | `/api/profile` | Get / update profile |
| `POST` | `/api/profile/password` | Change password |
| `GET` | `/api/containers` | List running containers |
| `WS` | `/api/containers/{id}/terminal` | Interactive container shell |
| `GET` | `/api/health` | DB / Docker / storage health |

## Project layout

```
backend/
  config.py           # env-driven configuration
  db.py               # MySQL connection + schema bootstrap
  security.py         # sessions, hashing, role checks
  services.py         # Docker / MySQL / storage / audit services
  console_server.py   # FastAPI app, API routes, WebSocket terminal
  .env.example
frontend/
  *.html              # console pages
  js/api.js           # shared API client
  js/*.js             # per-page logic
systemd/
  nimbus-console.service
```

## Resource limits

Compute instances are bounded by CPU (1–4 cores), RAM (1–8 GB) and storage
(1–100 GB); uploads are limited by `NIMBUS_MAX_UPLOAD_MB` and the per-user
storage quota. SQL console results are capped by `NIMBUS_MAX_QUERY_ROWS`.

## Security model

- **Roles**: `Administrator`, `Developer` (read/write) and `Viewer`
  (read-only). Self-signup is clamped to `Developer`/`Viewer` and defaults to
  `Viewer`; it can never create an `Administrator`.
- **Passwords**: stored as Werkzeug hashes; policy minimum is 4 characters
  (`NIMBUS_PASSWORD_MIN_LENGTH`), maximum 128. Changing a password revokes all
  other sessions.
- **Login throttling**: an identifier is locked after
  `NIMBUS_LOGIN_MAX_ATTEMPTS` failures within the window; login responses are
  generic and timing-balanced so they do not reveal whether an account exists.
- **SQL console**: non-administrator users cannot read the console's
  `nimbus_*` metadata tables or system schemas, and cannot run file
  (`INTO OUTFILE`, `LOAD_FILE`) or resource-exhaustion (`SLEEP`, `BENCHMARK`)
  statements. Viewer queries additionally run inside a MySQL
  `START TRANSACTION READ ONLY`.
- **Storage**: uploaded names are sanitised to a single safe path component and
  every read/write/delete is verified to stay within the user's directory.

## Tests

```bash
cd backend
../venv/bin/pip install pytest httpx
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../venv/bin/python -m pytest tests -q
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` avoids unrelated third-party pytest plugins
(e.g. ROS `launch_testing`) being auto-loaded from the system environment. The
suite covers password/username/email validation, login throttling, the SQL
query guard and read-only enforcement, storage path sanitisation and the main
API flows. The API tests create uniquely named users and remove them again.
