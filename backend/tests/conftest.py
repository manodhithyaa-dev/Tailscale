"""Shared pytest fixtures.

The unit tests only need ``security``/``services`` logic, but the API tests
exercise the real FastAPI app, which talks to MySQL and Docker.  Storage is
redirected to a throw-away temp directory so tests never touch real uploads.
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("NIMBUS_STORAGE_DIR", tempfile.mkdtemp(prefix="nimbus-tests-"))

import pytest  # noqa: E402

import db  # noqa: E402


@pytest.fixture()
def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


@pytest.fixture()
def cleanup_user():
    """Yield a registrar that deletes users created during a test."""
    created: list[str] = []

    def register(username: str) -> str:
        created.append(username)
        return username

    yield register

    for username in created:
        row = db.query_one(
            "SELECT id FROM nimbus_users WHERE username = %s", (username,), dictionary=True
        )
        if not row:
            continue
        uid = row["id"]
        db.execute("DELETE FROM nimbus_activity WHERE user_id = %s", (uid,))
        db.execute("DELETE FROM nimbus_files WHERE owner_id = %s", (uid,))
        db.execute("DELETE FROM nimbus_instances WHERE owner_id = %s", (uid,))
        db.execute("DELETE FROM nimbus_databases WHERE owner_id = %s", (uid,))
        db.execute("DELETE FROM nimbus_sessions WHERE user_id = %s", (uid,))
        db.execute("DELETE FROM nimbus_users WHERE id = %s", (uid,))
        import shutil

        import config  # noqa: E402

        shutil.rmtree(config.STORAGE_DIR / str(uid), ignore_errors=True)
