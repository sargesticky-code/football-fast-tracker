"""Phase 3 Layer 6 executable FotMob match-detail source.

Heavy-only source client. It is intentionally separate from the Fast Lane board
collector: callers must place it behind HeavyLane's >=30 second cadence and
request budget. This module performs no identity matching and creates no HKJC
eligibility.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

FOTMOB_MATCH_DETAILS_URL = "https://www.fotmob.com/api/matchDetails"


@dataclass
class FotMobHeavySourceDiagnostics:
    requests_attempted: int = 0
    requests_succeeded: int = 0
    requests_failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "requests_attempted": self.requests_attempted,
            "requests_succeeded": self.requests_succeeded,
            "requests_failed": self.requests_failed,
        }


class FotMobHeavySource:
    """Small injectable HTTP client for one budgeted matchDetails request.

    HeavyLane, not this class, owns cadence/rotation. Keeping the HTTP primitive
    stateless with respect to scheduling prevents an accidental second polling
    loop from being introduced here.
    """

    def __init__(self, *, timeout_seconds: float = 8.0,
                 opener: Callable[..., Any] = urlopen,
                 user_agent: str = "football-fast-tracker-phase3/1.0"):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = float(timeout_seconds)
        self.opener = opener
        self.user_agent = user_agent
        self.diagnostics = FotMobHeavySourceDiagnostics()

    def fetch_json(self, match_id: str) -> dict[str, Any]:
        match_id = str(match_id or "").strip()
        if not match_id.isdigit():
            raise ValueError("FotMob match_id must be numeric")
        url = FOTMOB_MATCH_DETAILS_URL + "?" + urlencode({"matchId": match_id})
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        self.diagnostics.requests_attempted += 1
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("FotMob matchDetails payload must be an object")
        except Exception:
            self.diagnostics.requests_failed += 1
            raise
        self.diagnostics.requests_succeeded += 1
        return payload
