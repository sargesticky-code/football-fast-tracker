"""Phase 3 Layer 4 consumer boundary for the shared lightweight heartbeat.

The service owns one SharedFastCache instance. HTTP/SSE adapters should call
``read()`` rather than invoking the Layer-3 collector directly, so concurrent
consumers cannot multiply upstream FotMob refreshes inside one backend process.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from phase3.shared_fast_cache import SharedFastCache


class FastHeartbeatService:
    """Process-local shared service for Phase-3 lightweight fast state."""

    def __init__(self, refresh: Callable[[], Mapping[str, Any]], lease_seconds: float = 5.0, clock=None):
        kwargs = {} if clock is None else {"clock": clock}
        self._cache = SharedFastCache(refresh, lease_seconds=lease_seconds, **kwargs)

    def read(self) -> dict[str, Any]:
        """Return consumer-ready state plus lease diagnostics."""
        result = self._cache.get()
        state = dict(result.state)
        state["shared_cache"] = {
            "status": result.cache_status,
            "lease_age_seconds": result.lease_age_seconds,
            "upstream_refreshes": result.upstream_refreshes,
        }
        return state
