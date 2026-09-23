"""Phase 3 Layer 4 shared fast-state lease.

Centralises lightweight upstream refreshes so concurrent consumers share one
refresh.  This deliberately does not fetch HKJC/heavy endpoints and does not
perform identity matching; the supplied refresh function owns the Layer-3
collector/service operation.
"""
from __future__ import annotations

import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class SharedFastResult:
    state: Mapping[str, Any]
    cache_status: str
    lease_age_seconds: float
    upstream_refreshes: int


class SharedFastCache:
    """Thread-safe, single-flight cache for the lightweight Phase-3 heartbeat."""

    def __init__(self, refresh: Callable[[], Mapping[str, Any]], lease_seconds: float = 5.0, clock: Callable[[], float] = time.monotonic):
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self._refresh = refresh
        self._lease_seconds = float(lease_seconds)
        self._clock = clock
        self._condition = threading.Condition()
        self._state: dict[str, Any] | None = None
        self._stored_at: float | None = None
        self._refreshing = False
        self._upstream_refreshes = 0

    def _fresh_locked(self, now: float) -> bool:
        return self._state is not None and self._stored_at is not None and 0 <= now - self._stored_at < self._lease_seconds

    def get(self) -> SharedFastResult:
        """Return shared fast state; at most one caller performs an expired refresh."""
        with self._condition:
            now = self._clock()
            if self._fresh_locked(now):
                return self._result_locked("HIT", now)
            if self._refreshing:
                while self._refreshing:
                    self._condition.wait()
                now = self._clock()
                if self._fresh_locked(now):
                    return self._result_locked("SHARED_AFTER_WAIT", now)
                # The leader failed. Preserve old state if available; otherwise
                # the waiter may become the next leader and make one retry.
                if self._state is not None:
                    return self._result_locked("STALE_AFTER_ERROR", now)
            self._refreshing = True

        try:
            candidate = dict(self._refresh())
            completed_at = self._clock()
            with self._condition:
                self._state = candidate
                self._stored_at = completed_at
                self._upstream_refreshes += 1
                self._refreshing = False
                self._condition.notify_all()
                return self._result_locked("REFRESH", completed_at)
        except Exception:
            with self._condition:
                self._refreshing = False
                self._condition.notify_all()
                now = self._clock()
                if self._state is not None:
                    return self._result_locked("STALE_AFTER_ERROR", now)
            raise

    def _result_locked(self, status: str, now: float) -> SharedFastResult:
        age = 0.0 if self._stored_at is None else max(0.0, now - self._stored_at)
        return SharedFastResult(deepcopy(self._state or {}), status, age, self._upstream_refreshes)
