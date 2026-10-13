"""Legacy standalone upload server (kept for reference). The web console now handles storage
through app.py with per-user folders, quotas and authentication - prefer that."""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

DEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "legacy_uploads")
os.makedirs(DEST, exist_ok=True)


class StorageServer(BaseHTTPRequestHandler):
    def do_POST(self):
        filename = os.path.basename(self.path.lstrip("/")) or "upload.bin"   # no path traversal
        size = int(self.headers.get("Content-Length", 0))
        if size > 100 * 1024 * 1024:
            self.send_response(413); self.end_headers(); return
        with open(os.path.join(DEST, filename), "wb") as f:
            f.write(self.rfile.read(size))
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Upload successful")


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8000), StorageServer).serve_forever()
