"""Run one SQL statement against a managed SQLite file or an external MySQL server."""
import re
import sqlite3
import time

import db

MAX_ROWS = 1000
TIMEOUT = 5
SAFE_PRAGMAS = {"table_info", "table_xinfo", "table_list", "index_list", "index_info", "foreign_key_list"}


class QueryError(Exception):
    pass


def _clean(v):
    return "0x" + v.hex() if isinstance(v, (bytes, bytearray, memoryview)) else v


def _pack(cur, started):
    cols = [d[0] for d in cur.description] if cur.description else []
    rows, truncated = [], False
    if cols:
        fetched = cur.fetchmany(MAX_ROWS + 1)
        truncated = len(fetched) > MAX_ROWS
        rows = [[_clean(v) for v in r] for r in fetched[:MAX_ROWS]]
    msg = "" if cols else f"Statement OK. {max(cur.rowcount, 0)} row(s) affected."
    return {"columns": cols, "rows": rows, "message": msg, "truncated": truncated,
            "ms": int((time.time() - started) * 1000)}


# ---------------------------------------------------------------- SQLite
def create_sqlite(path):
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version=1")
    con.commit()
    con.close()


def _authorizer(action, a1, a2, dbname, src):
    if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA and (a1 or "").lower() not in SAFE_PRAGMAS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and (a2 or "").lower() == "load_extension":
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def run_sqlite(path, query, readonly=False):
    stripped = re.sub(r"--[^\n]*|/\*.*?\*/", " ", query, flags=re.S).strip()
    if re.match(r"(vacuum|attach|detach)\b", stripped, re.I):
        raise QueryError("This statement is not allowed in the console.")
    started = time.time()
    con = sqlite3.connect(f"file:{path}?mode={'ro' if readonly else 'rw'}", uri=True, timeout=3)
    try:
        con.execute("PRAGMA max_page_count=25600")          # ~100 MB cap per database
        con.set_authorizer(_authorizer)
        deadline = started + TIMEOUT
        con.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10000)
        cur = con.execute(query)                            # exactly one statement
        result = _pack(cur, started)
        con.commit()
        return result
    except sqlite3.Error as exc:
        con.rollback()
        if "interrupted" in str(exc).lower():
            raise QueryError(f"Query exceeded the {TIMEOUT}s time limit.")
        raise QueryError(str(exc))
    finally:
        con.close()


def tables_sqlite(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    finally:
        con.close()


# ---------------------------------------------------------------- MySQL
def _mysql_conn(cfg):
    try:
        import mysql.connector
    except ImportError:
        raise QueryError("mysql-connector-python is not installed (pip install mysql-connector-python).")
    try:
        return mysql.connector.connect(
            host=cfg["host"], port=cfg["port"] or 3306, user=cfg["db_username"],
            password=db.decrypt(cfg["db_password_enc"]), database=cfg["db_name"], connection_timeout=5)
    except mysql.connector.Error as exc:
        raise QueryError(f"MySQL connection failed: {exc}")


def test_mysql(cfg):
    _mysql_conn(cfg).close()


def run_mysql(cfg, query):
    import mysql.connector
    started = time.time()
    con = _mysql_conn(cfg)
    try:
        cur = con.cursor()
        cur.execute(query)
        result = _pack(cur, started)
        con.commit()
        return result
    except mysql.connector.Error as exc:
        con.rollback()
        raise QueryError(f"MySQL error: {exc}")
    finally:
        con.close()


def tables_mysql(cfg):
    con = _mysql_conn(cfg)
    try:
        cur = con.cursor()
        cur.execute("SHOW TABLES")
        return [r[0] for r in cur.fetchall()]
    finally:
        con.close()
