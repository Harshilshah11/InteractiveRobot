"""HTTP -> HTTPS redirect, so typing the bare domain still lands on the app.

Listens on 127.0.0.1 only; scripts/local-domain.sh forwards port 80 here.
"""

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOMAIN = sys.argv[1] if len(sys.argv) > 1 else "arnobotinteractiverobot.com"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8080


class Redirect(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server's naming
        host = (self.headers.get("Host") or DOMAIN).split(":")[0]
        self.send_response(301)
        self.send_header("Location", f"https://{host}{self.path}")
        self.end_headers()

    do_HEAD = do_GET

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Redirect).serve_forever()
