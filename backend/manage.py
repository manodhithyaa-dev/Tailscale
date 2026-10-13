"""Admin helper:  python manage.py list | create <user> <email> <role> | set-role <user> <role> | passwd <user>"""
import getpass
import sqlite3
import sys
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash

import db

ROLES = ("Administrator", "Developer", "Viewer")
db.init_db()
a = sys.argv[1:]
try:
    if a[:1] == ["list"]:
        for u in db.q("SELECT username,email,role,created_at FROM users"):
            print(f"{u['username']:<20} {u['role']:<14} {u['email']}")
    elif a[:1] == ["set-role"] and len(a) == 3 and a[2] in ROLES:
        db.execute("UPDATE users SET role=? WHERE username=?", (a[2], a[1])); print("done")
    elif a[:1] == ["passwd"] and len(a) == 2:
        pw = getpass.getpass("New password (min 8): ")
        assert len(pw) >= 8, "too short"
        db.execute("UPDATE users SET password_hash=? WHERE username=?", (generate_password_hash(pw), a[1])); print("done")
    elif a[:1] == ["create"] and len(a) == 4 and a[3] in ROLES:
        pw = getpass.getpass("Password (min 8): ")
        assert len(pw) >= 8, "too short"
        db.execute("INSERT INTO users(username,email,full_name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)",
                   (a[1], a[2], a[1], generate_password_hash(pw), a[3], datetime.now(timezone.utc).isoformat(timespec="seconds"))); print("created")
    else:
        print(__doc__)
except (sqlite3.IntegrityError, AssertionError) as e:
    print("Error:", e)
