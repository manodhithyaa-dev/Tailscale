"""Central configuration for the Nimbus private-cloud console.

Values are read from environment variables (optionally from a ``.env`` file
next to this module) so the same code can run on the Tailscale host without
hard-coding credentials.
"""

import os
from pathlib import Path

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"))
except Exception:  # pragma: no cover - dotenv is a convenience only
    pass


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = (BASE_DIR.parent / "frontend").resolve()
STORAGE_DIR = Path(os.environ.get("NIMBUS_STORAGE_DIR", BASE_DIR / "storage")).resolve()

# ---------------------------------------------------------------------------
# MySQL (console metadata + SQL console target)
# ---------------------------------------------------------------------------
MYSQL_HOST = os.environ.get("NIMBUS_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("NIMBUS_MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("NIMBUS_MYSQL_USER", "clouduser")
MYSQL_PASSWORD = os.environ.get("NIMBUS_MYSQL_PASSWORD", "your_password")
MYSQL_DATABASE = os.environ.get("NIMBUS_MYSQL_DATABASE", "cloud_db")
MYSQL_CONNECT_TIMEOUT = int(os.environ.get("NIMBUS_MYSQL_CONNECT_TIMEOUT", "8"))

# ---------------------------------------------------------------------------
# Sessions / security
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("NIMBUS_SECRET_KEY", "nimbus-dev-secret-change-me")
SESSION_COOKIE = os.environ.get("NIMBUS_SESSION_COOKIE", "nimbus_session")
SESSION_TTL_HOURS = int(os.environ.get("NIMBUS_SESSION_TTL_HOURS", "168"))
COOKIE_SECURE = os.environ.get("NIMBUS_COOKIE_SECURE", "0") == "1"

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
QUOTA_BYTES = int(float(os.environ.get("NIMBUS_QUOTA_GB", "100")) * 1024**3)
MAX_QUERY_ROWS = int(os.environ.get("NIMBUS_MAX_QUERY_ROWS", "500"))
MAX_UPLOAD_BYTES = int(float(os.environ.get("NIMBUS_MAX_UPLOAD_MB", "200")) * 1024**2)

# Compute limits for provisioned instances
MIN_CPU, MAX_CPU = 1, 4
MIN_RAM_GB, MAX_RAM_GB = 1, 8
MIN_STORAGE_GB, MAX_STORAGE_GB = 1, 100

ROLES = ("Administrator", "Developer", "Viewer")
WRITE_ROLES = ("Administrator", "Developer")
ADMIN_ROLES = ("Administrator",)
SELF_SIGNUP_ROLES = ("Developer", "Viewer")
DEFAULT_SIGNUP_ROLE = "Viewer"

# ---------------------------------------------------------------------------
# Password policy
#
# NOTE: the product requirement is a *minimum* of four characters.  Four
# character passwords are extremely weak, so a generous maximum is enforced to
# prevent hashing-based denial of service, and compensating controls (login
# rate limiting / lockout, session expiry) are implemented in ``security.py``.
# ---------------------------------------------------------------------------
PASSWORD_MIN_LENGTH = int(os.environ.get("NIMBUS_PASSWORD_MIN_LENGTH", "4"))
PASSWORD_MAX_LENGTH = int(os.environ.get("NIMBUS_PASSWORD_MAX_LENGTH", "128"))

# Login throttling: after ``LOGIN_MAX_ATTEMPTS`` failures within
# ``LOGIN_WINDOW_SECONDS`` the identifier is locked for ``LOGIN_LOCKOUT_SECONDS``.
LOGIN_MAX_ATTEMPTS = int(os.environ.get("NIMBUS_LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SECONDS = int(os.environ.get("NIMBUS_LOGIN_WINDOW_SECONDS", "300"))
LOGIN_LOCKOUT_SECONDS = int(os.environ.get("NIMBUS_LOGIN_LOCKOUT_SECONDS", "300"))
