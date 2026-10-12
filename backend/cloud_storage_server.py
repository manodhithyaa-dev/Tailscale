from http.server import HTTPServer, BaseHTTPRequestHandler

class StorageServer(BaseHTTPRequestHandler):
    def do_POST(self):
        filename = self.path.lstrip("/")
        size = int(self.headers["Content-Length"])

        with open(filename, "wb") as f:
            f.write(self.rfile.read(size))

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Upload successful")

HTTPServer(("0.0.0.0", 8000), StorageServer).serve_forever()