"""Phase 3 Layer 5 read-only API adapter for shared fast heartbeat state.

Adapters must receive a FastHeartbeatService (or compatible object exposing
read()).  They never call an upstream collector directly.  This preserves the
Layer-4 shared lease boundary for HTTP/SSE/dashboard consumers.
"""
from __future__ import annotations

from typing import Any, Protocol

from phase3.fast_consumer import project_fast_state


class FastStateReader(Protocol):
    def read(self) -> dict[str, Any]: ...


def fast_api_payload(service: FastStateReader) -> dict[str, Any]:
    """Read shared heartbeat state once and return the Layer-5 JSON contract."""
    return project_fast_state(service.read())


def fast_api_response(service: FastStateReader) -> tuple[int, dict[str, str], dict[str, Any]]:
    """Return an HTTP-adapter-friendly status, headers and JSON body.

    Source/identity gaps remain HTTP 200 because they are valid fail-closed
    observations that dashboards must render.  Only an unavailable service
    call becomes 503; no fallback collector call is attempted.
    """
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
    }
    try:
        payload = fast_api_payload(service)
    except Exception as exc:  # boundary: never bypass shared service on failure
        return 503, headers, {
            "display_state": "REQUEST_FAILED",
            "health": "SERVICE_UNAVAILABLE",
            "error": type(exc).__name__,
            "matches": [],
        }
    return 200, headers, payload
