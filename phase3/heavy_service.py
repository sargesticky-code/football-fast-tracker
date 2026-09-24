"""Phase 3 Layer 6 executable heavy collection service.

This is the composition boundary for the Heavy Lane. It deliberately keeps
FotMob matchDetails behind HeavyLane's >=30 second cadence/request budget and
consumes only already-authorised Fast Lane state via HeavyCollector.
"""
from __future__ import annotations

from typing import Any, Mapping

from phase3.fotmob_heavy import make_fotmob_detail_fetcher
from phase3.fotmob_heavy_source import FotMobHeavySource
from phase3.heavy_collector import HeavyCollector
from phase3.heavy_lane import HeavyLane


class HeavyService:
    """Compose source -> normalizer -> cadence/budget -> verified target gate."""

    def __init__(self, *, source: FotMobHeavySource | None = None,
                 min_interval_seconds: float = 45.0,
                 max_requests_per_cycle: int = 2):
        self.source = source or FotMobHeavySource()
        detail_fetcher = make_fotmob_detail_fetcher(self.source.fetch_json)
        self.lane = HeavyLane(
            detail_fetcher,
            min_interval_seconds=min_interval_seconds,
            max_requests_per_cycle=max_requests_per_cycle,
        )
        self.collector = HeavyCollector(self.lane)

    def collect(self, fast_state: Mapping[str, Any], *, now: Any = None) -> dict[str, Any]:
        """Collect one bounded heavy cycle from current Fast Lane state.

        Source request counters are returned as cycle deltas as well as lifetime
        totals. This makes it possible to prove the Heavy Lane did not fan out
        beyond the configured request budget.
        """
        before = self.source.diagnostics.as_dict()
        result = self.collector.collect(fast_state, now=now)
        after = self.source.diagnostics.as_dict()
        result["source_requests"] = {
            "attempted": after["requests_attempted"] - before["requests_attempted"],
            "succeeded": after["requests_succeeded"] - before["requests_succeeded"],
            "failed": after["requests_failed"] - before["requests_failed"],
        }
        result["source_requests_total"] = after
        # requests_used is HeavyLane's budget accounting; source_attempted is the
        # actual HTTP primitive count. A mismatch is exposed rather than hidden.
        result["request_count_consistent"] = (
            result.get("requests_used") == result["source_requests"]["attempted"]
        )
        return result
