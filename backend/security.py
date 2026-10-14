"""Password hashing and database-backed session management.

Sessions are opaque random tokens persisted in MySQL, which makes them
revocable and consistent across worker processes (unlike in-memory state).
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from werkzeug.security import check_password_hash, generate_password_hash

import config
import db


class AuthError(Exception):
    """Authentication or request validation failure."""


class Forbidden(AuthError):
    """The authenticated user is not allowed to perform the action."""


class RateLimited(Exception):
    """Too many requests from a client; retry later."""


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return check_password_hash(password_hash, password)
    except Exception:  # malformed hash
        return False


# A precomputed hash for a throwaway value.  Verifying against it when an
# account does not exist keeps the login timing roughly constant so the API
# does not reveal whether a username/email is registered.
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))

USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,59}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_username(username: str) -> None:
    if not USERNAME_RE.fullmatch(username or ""):
        raise AuthError(
            "Username must be 3-60 characters and use letters, digits, '.', '_' or '-'."
        )


def validate_email(email: str) -> None:
    if not EMAIL_RE.fullmatch((email or "").strip()):
        raise AuthError("Please enter a valid email address.")


def validate_password(password: str) -> None:
    """Enforce the documented password policy.

    The requirement is a *minimum of four characters* (see ``config``).  The
    maximum prevents extremely large inputs from being hashed.
    """
    if not isinstance(password, str):
        raise AuthError("Password must be text.")
    if len(password) < config.PASSWORD_MIN_LENGTH:
        raise AuthError(
            f"Password must be at least {config.PASSWORD_MIN_LENGTH} characters long."
        )
    if len(password) > config.PASSWORD_MAX_LENGTH:
        raise AuthError(
            f"Password must be at most {config.PASSWORD_MAX_LENGTH} characters long."
        )


def authenticate(identifier: str, password: str) -> Optional[dict[str, Any]]:
    """Return the matching user for valid credentials, else ``None``.

    Always performs a hash comparison so the response time does not disclose
    whether the identifier exists.
    """
    record = db.query_one(
        "SELECT * FROM nimbus_users WHERE username = %s OR email = %s",
        (identifier, identifier),
        dictionary=True,
    )
    if record is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, record["password_hash"]):
        return None
    strip = {"password_hash"}
    return {k: v for k, v in record.items() if k not in strip}


# ---------------------------------------------------------------------------
# Login throttling (in-process; the console runs as a single uvicorn worker)
# ---------------------------------------------------------------------------

class LoginThrottle:
    """Progressive lockout keyed by the attempted identifier.

    Keys expire after ``LOGIN_LOCKOUT_SECONDS`` and failure timestamps are
    pruned to the sliding ``LOGIN_WINDOW_SECONDS`` window.  This limits brute
    force against a single account without providing an attacker a cheap way
    to lock out unrelated accounts.
    """

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(identifier: str) -> str:
        return (identifier or "").strip().lower()

    def is_locked(self, identifier: str) -> int:
        """Return remaining lock seconds (0 when not locked)."""
        key = self._key(identifier)
        now = time.monotonic()
        with self._lock:
            until = self._locked_until.get(key, 0.0)
            if until and until > now:
                return int(until - now) + 1
            if until:
                self._locked_until.pop(key, None)
                self._failures.pop(key, None)
            return 0

    def register_failure(self, identifier: str) -> None:
        key = self._key(identifier)
        now = time.monotonic()
        with self._lock:
            recent = [
                t for t in self._failures.get(key, [])
                if now - t <= config.LOGIN_WINDOW_SECONDS
            ]
            recent.append(now)
            self._failures[key] = recent
            if len(recent) >= config.LOGIN_MAX_ATTEMPTS:
                self._locked_until[key] = now + config.LOGIN_LOCKOUT_SECONDS
                self._failures[key] = []

    def reset(self, identifier: str) -> None:
        key = self._key(identifier)
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)


login_throttle = LoginThrottle()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    # Store a naive UTC timestamp to match MySQL's UTC_TIMESTAMP() comparisons.
    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        hours=config.SESSION_TTL_HOURS
    )
    db.execute(
        "INSERT INTO nimbus_sessions (token, user_id, expires_at) VALUES (%s, %s, %s)",
        (token, user_id, expires),
    )
    return token


def destroy_session(token: str) -> None:
    if not token:
        return
    db.execute("DELETE FROM nimbus_sessions WHERE token = %s", (token,))


def destroy_user_sessions(user_id: int) -> None:
    db.execute("DELETE FROM nimbus_sessions WHERE user_id = %s", (user_id,))


def purge_expired_sessions() -> None:
    db.execute("DELETE FROM nimbus_sessions WHERE expires_at < UTC_TIMESTAMP()")


def user_from_token(token: Optional[str]) -> Optional[dict[str, Any]]:
    if not token:
        return None
    row = db.query_one(
        """
        SELECT u.id, u.name, u.username, u.email, u.role, u.notify_enabled,
               u.created_at
        FROM nimbus_sessions s
        JOIN nimbus_users u ON u.id = s.user_id
        WHERE s.token = %s AND s.expires_at > UTC_TIMESTAMP()
        """,
        (token,),
        dictionary=True,
    )
    return row


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user_by_id(user_id: int) -> Optional[dict[str, Any]]:
    return db.query_one(
        "SELECT id, name, username, email, role, notify_enabled, created_at "
        "FROM nimbus_users WHERE id = %s",
        (user_id,),
        dictionary=True,
    )


def get_user_by_identifier(identifier: str) -> Optional[dict[str, Any]]:
    return db.query_one(
        "SELECT * FROM nimbus_users WHERE username = %s OR email = %s",
        (identifier, identifier),
        dictionary=True,
    )


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "name": user["name"],
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "notifyEnabled": bool(user.get("notify_enabled", 1)),
    }


# ---------------------------------------------------------------------------
# Role helpers
# ---------------------------------------------------------------------------

def can_write(user: dict[str, Any]) -> bool:
    return user["role"] in config.WRITE_ROLES


def is_admin(user: dict[str, Any]) -> bool:
    return user["role"] in config.ADMIN_ROLES


def require_write(user: dict[str, Any]) -> None:
    if not can_write(user):
        raise Forbidden("Your role does not allow this action.")


def require_admin(user: dict[str, Any]) -> None:
    if not is_admin(user):
        raise Forbidden("Administrator access is required.")
