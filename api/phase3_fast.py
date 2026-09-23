"""Phase 3 Layer 5 read-only HTTP endpoint for the shared fast heartbeat.

This endpoint is deliberately isolated from legacy ``api/live_scores.py`` and
never calls FotMob/HKJC directly.  It consumes the latest Layer-3 snapshot
through the Layer-4 shared service boundary, so browser requests cannot create
upstream fan-out.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
from typing import Any

from phase3.fast_api import fast_api_response
from phase3.fast_service import FastHeartbeatService

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "phase3_fast_snapshot.json"


def _read_snapshot() -> dict[str, Any]:
    if not SNAPSHOT.exists():
        return {
            "health": "NO_SNAPSHOT",
            "rows": [],
            "mapped_rows": 0,
            "live_rows": 0,
            "unmapped_count": 0,
            "unmapped_external_ids": [],
            "missing_target_ids": [],
            "request_failures": 0,
        }
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("phase3 fast snapshot must be a JSON object")
    return payload


# Process-local singleton: all requests handled by a warm backend instance share
# the same five-second lease.  The refresh is a local snapshot read only; source
# collection remains centralized outside the browser request path.
_SERVICE = FastHeartbeatService(_read_snapshot, lease_seconds=5.0)


def http_response(service=_SERVICE):
    """Expose a testable HTTP response tuple without starting a server."""
    return fast_api_response(service)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, headers, payload = http_response()
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        status, headers, _ = http_response()
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
