import json
import os
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

from api.live_scores import UPSTREAM_BUILD, handler as LiveHandler


class RailwayLiveHandler(LiveHandler):
    def do_GET(self):
        if urlparse(self.path).path == "/health":
            body = json.dumps({
                "ok": True,
                "service": "football-fast-tracker-live",
                "buildVersion": UPSTREAM_BUILD,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), RailwayLiveHandler)
    server.serve_forever()
