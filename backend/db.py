"""SQLite metadata store: users, instances, files, databases, activity."""
import os
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet
from flask import g

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("NIMBUS_DATA", BASE / "data")).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "nimbus.db"
STORAGE_DIR = DATA / "storage"      # uploaded files, one folder per user id
USERDB_DIR = DATA / "userdbs"       # managed SQLite databases
STORAGE_DIR.mkdir(exist_ok=True)
USERDB_DIR.mkdir(exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  full_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('Administrator','Developer','Viewer')),
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS instances(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  instance_id TEXT NOT NULL UNIQUE,
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  container_name TEXT NOT NULL UNIQUE,
  os TEXT NOT NULL, cpu REAL NOT NULL, ram_mb INTEGER NOT NULL, storage_gb INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(owner_id, name));
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, stored_name TEXT, type TEXT NOT NULL,
  size INTEGER NOT NULL DEFAULT 0, is_folder INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS databases(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, engine TEXT NOT NULL CHECK(engine IN ('sqlite','mysql')),
  host TEXT, port INTEGER, db_username TEXT, db_password_enc TEXT, db_name TEXT,
  path TEXT, created_at TEXT NOT NULL,
  UNIQUE(owner_id, name));
CREATE TABLE IF NOT EXISTS activity(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER, username TEXT NOT NULL,
  action TEXT NOT NULL, resource TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'Success', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_activity_user ON activity(user_id, id);
"""


def connect():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db():
    con = connect()
    con.executescript(SCHEMA)
    con.commit()
    con.close()


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def _own():
    """Connection usable both inside and outside a Flask request."""
    try:
        return get_db(), False
    except RuntimeError:
        return connect(), True


def q(sql, args=()):
    con, own = _own()
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        if own:
            con.close()


def q1(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def execute(sql, args=()):
    con, own = _own()
    try:
        cur = con.execute(sql, args)
        con.commit()
        return cur.lastrowid
    finally:
        if own:
            con.close()


def _key_file(name):
    p = DATA / name
    if not p.exists():
        p.write_bytes(Fernet.generate_key() if name == "fernet.key" else os.urandom(32).hex().encode())
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    return p.read_bytes().strip()


def get_secret_key():
    return _key_file("secret.key").decode()


def encrypt(text):
    return Fernet(_key_file("fernet.key")).encrypt(text.encode()).decode()


def decrypt(token):
    return Fernet(_key_file("fernet.key")).decrypt(token.encode()).decode()
