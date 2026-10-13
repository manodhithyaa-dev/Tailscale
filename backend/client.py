"""Upload a file to the Nimbus storage API from the command line.

  python client.py path/to/file.pdf            (server: $NIMBUS_SERVER or http://127.0.0.1:5000)
Over Tailscale: set NIMBUS_SERVER=http://<server-tailscale-ip>:5000
"""
import getpass
import os
import sys

import requests

server = os.environ.get("NIMBUS_SERVER", "http://127.0.0.1:5000").rstrip("/")
if len(sys.argv) != 2 or not os.path.isfile(sys.argv[1]):
    sys.exit(__doc__)
s = requests.Session()
s.headers["X-Requested-With"] = "nimbus"
r = s.post(f"{server}/api/login", json={"user": input("Username: "), "password": getpass.getpass("Password: ")})
if not r.ok:
    sys.exit(r.json().get("error", r.text))
with open(sys.argv[1], "rb") as fh:
    r = s.post(f"{server}/api/files", files={"files": (os.path.basename(sys.argv[1]), fh)})
print(r.json().get("error") or "Upload successful")
