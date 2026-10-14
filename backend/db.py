"""MySQL access layer for the Nimbus console.

All console metadata (users, sessions, per-user resource registry and the
activity audit trail) lives in a single MySQL schema.  Tables are created on
startup with ``CREATE TABLE IF NOT EXISTS`` so the module is self-provisioning.

Every helper opens a short-lived connection.  This is slightly less efficient
than pooling but keeps request handling simple and thread-safe, which matters
because FastAPI runs the synchronous endpoints in a worker thread pool.
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator, Sequence

import mysql.connector
from mysql.connector import Error

import config


class DatabaseUnavailable(RuntimeError):
    """Raised when MySQL cannot be reached or a statement fails."""


def connect(database: str | None = None) -> mysql.connector.MySQLConnection:
    """Open a new MySQL connection.

    ``database`` defaults to the console schema; pass ``None`` explicitly to
    connect without selecting a schema.
    """
    try:
        return mysql.connector.connect(
            host=config.MYSQL_HOST,
            port=config.MYSQL_PORT,
            user=config.MYSQL_USER,
            password=config.MYSQL_PASSWORD,
            database=config.MYSQL_DATABASE if database is None else database,
            connection_timeout=config.MYSQL_CONNECT_TIMEOUT,
            autocommit=False,
        )
    except Error as exc:  # pragma: no cover - depends on environment
        raise DatabaseUnavailable(str(exc)) from exc


@contextlib.contextmanager
def cursor(dictionary: bool = False, commit: bool = False) -> Iterator[Any]:
    """Yield a cursor inside a transaction, committing or rolling back."""
    connection = connect()
    cur = connection.cursor(dictionary=dictionary, buffered=True)
    try:
        yield cur
        if commit:
            connection.commit()
    except Exception:
        with contextlib.suppress(Exception):
            connection.rollback()
        raise
    finally:
        with contextlib.suppress(Exception):
            cur.close()
        with contextlib.suppress(Exception):
            connection.close()


def query_all(sql: str, params: Sequence[Any] = (), dictionary: bool = False) -> list[Any]:
    with cursor(dictionary=dictionary) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def query_one(sql: str, params: Sequence[Any] = (), dictionary: bool = False):
    with cursor(dictionary=dictionary) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql: str, params: Sequence[Any] = ()) -> int:
    """Run a write statement and return the last insert id / affected count."""
    with cursor(commit=True) as cur:
        cur.execute(sql, params)
        return cur.lastrowid


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS nimbus_users (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        name          VARCHAR(120) NOT NULL,
        username      VARCHAR(60)  NOT NULL UNIQUE,
        email         VARCHAR(190) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        role          ENUM('Administrator','Developer','Viewer') NOT NULL DEFAULT 'Viewer',
        notify_enabled TINYINT(1) NOT NULL DEFAULT 1,
        created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS nimbus_sessions (
        token      CHAR(64) PRIMARY KEY,
        user_id    INT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at DATETIME NOT NULL,
        CONSTRAINT fk_session_user FOREIGN KEY (user_id)
            REFERENCES nimbus_users(id) ON DELETE CASCADE,
        INDEX idx_session_user (user_id)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS nimbus_instances (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        owner_id     INT NOT NULL,
        name         VARCHAR(64) NOT NULL,
        container_id VARCHAR(80),
        os           VARCHAR(40) NOT NULL,
        cpu          DECIMAL(4,1) NOT NULL DEFAULT 1,
        ram_gb       INT NOT NULL DEFAULT 1,
        storage_gb   INT NOT NULL DEFAULT 10,
        status       VARCHAR(20) NOT NULL DEFAULT 'Stopped',
        ip           VARCHAR(45),
        created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uniq_owner_instance (owner_id, name),
        CONSTRAINT fk_instance_user FOREIGN KEY (owner_id)
            REFERENCES nimbus_users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS nimbus_files (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        owner_id    INT NOT NULL,
        name        VARCHAR(255) NOT NULL,
        kind        VARCHAR(24)  NOT NULL DEFAULT 'Document',
        size_bytes  BIGINT NOT NULL DEFAULT 0,
        stored_path VARCHAR(500) NOT NULL,
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_file_user FOREIGN KEY (owner_id)
            REFERENCES nimbus_users(id) ON DELETE CASCADE,
        INDEX idx_file_owner (owner_id)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS nimbus_databases (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        owner_id    INT NOT NULL,
        name        VARCHAR(64) NOT NULL,
        db_type     VARCHAR(30) NOT NULL DEFAULT 'MySQL',
        host        VARCHAR(120) NOT NULL,
        port        INT NOT NULL DEFAULT 3306,
        schema_name VARCHAR(64) NOT NULL,
        status      VARCHAR(20) NOT NULL DEFAULT 'Running',
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uniq_owner_database (owner_id, name),
        CONSTRAINT fk_database_user FOREIGN KEY (owner_id)
            REFERENCES nimbus_users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS nimbus_activity (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        user_id    INT NULL,
        username   VARCHAR(120) NOT NULL,
        action     VARCHAR(80)  NOT NULL,
        resource   VARCHAR(160) NULL,
        status     VARCHAR(20)  NOT NULL DEFAULT 'Success',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_activity_user FOREIGN KEY (user_id)
            REFERENCES nimbus_users(id) ON DELETE SET NULL,
        INDEX idx_activity_user (user_id),
        INDEX idx_activity_created (created_at)
    ) ENGINE=InnoDB
    """,
]


def init_schema() -> None:
    """Create every console table if it does not already exist."""
    with cursor(commit=True) as cur:
        for statement in SCHEMA_STATEMENTS:
            cur.execute(statement)


def ping() -> tuple[bool, str]:
    """Return (healthy, message) for the console database."""
    try:
        row = query_one("SELECT VERSION()")
        return True, row[0] if row else "unknown"
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        return False, str(exc)
