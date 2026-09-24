"""Phase 3 Layer 6 source-safe heavy live-stat scheduling.

Heavy observations are independent from the 5-second Fast Lane.  This module
only schedules HKJC-authorised matches that already have VERIFIED persistent
external identities; it never performs fuzzy identity matching or creates HKJC
eligibility.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

HEAVY_FIELDS = (
    "xg", "shots", "shots_on_target", "possession", "box_touches",
    "big_chances", "corners", "events", "momentum",
)


def _utc(value: Any = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class HeavyTarget:
    hkjc_event_id: str
    external_source: str
    external_id: str
    identity_status: str = "VERIFIED"
    hkjc_authorised: bool = True


class HeavyLane:
    """Bounded round-robin heavy collector with per-match cadence guards."""

    def __init__(self, fetch_detail: Callable[[HeavyTarget], dict[str, Any]], *,
                 min_interval_seconds: float = 45.0, max_requests_per_cycle: int = 2):
        if min_interval_seconds < 30:
            raise ValueError("heavy cadence must be >= 30 seconds")
        if max_requests_per_cycle < 1:
            raise ValueError("request budget must be positive")
        self.fetch_detail = fetch_detail
        self.min_interval_seconds = float(min_interval_seconds)
        self.max_requests_per_cycle = int(max_requests_per_cycle)
        self._last_attempt: dict[str, datetime] = {}
        self._cursor = 0

    @staticmethod
    def _eligible(target: HeavyTarget) -> bool:
        return bool(target.hkjc_authorised and target.identity_status == "VERIFIED"
                    and target.hkjc_event_id and target.external_id)

    def collect(self, targets: Iterable[HeavyTarget], *, now: Any = None) -> dict[str, Any]:
        observed = _utc(now)
        all_targets = list(targets)
        eligible = [t for t in all_targets if self._eligible(t)]
        rejected = [t.hkjc_event_id for t in all_targets if not self._eligible(t)]
        if eligible:
            start = self._cursor % len(eligible)
            rotated = eligible[start:] + eligible[:start]
        else:
            rotated = []
        rows, failures, deferred = [], [], []
        attempted = 0
        for target in rotated:
            key = f"{target.external_source}:{target.external_id}"
            previous = self._last_attempt.get(key)
            if previous is not None and (observed - previous).total_seconds() < self.min_interval_seconds:
                deferred.append(target.hkjc_event_id)
                continue
            if attempted >= self.max_requests_per_cycle:
                deferred.append(target.hkjc_event_id)
                continue
            attempted += 1
            self._last_attempt[key] = observed
            try:
                payload = self.fetch_detail(target) or {}
                stats = {field: payload.get(field) for field in HEAVY_FIELDS}
                usable = any(value is not None for value in stats.values())
                rows.append({
                    "hkjc_event_id": target.hkjc_event_id,
                    "external_source": target.external_source,
                    "external_id": target.external_id,
                    "heavy_observed_at": observed.isoformat().replace("+00:00", "Z"),
                    "heavy_status": "USABLE" if usable else "DETAIL_EMPTY",
                    **stats,
                })
            except Exception as exc:  # source failure is diagnostic, never fabricated data
                failures.append({"hkjc_event_id": target.hkjc_event_id, "error": type(exc).__name__})
        if eligible:
            self._cursor = (self._cursor + attempted) % len(eligible)
        return {
            "heavy_observed_at": observed.isoformat().replace("+00:00", "Z"),
            "heavy_rows": rows,
            "heavy_usable_rows": sum(r["heavy_status"] == "USABLE" for r in rows),
            "detail_empty_rows": sum(r["heavy_status"] == "DETAIL_EMPTY" for r in rows),
            "source_gap_rows": len(failures),
            "request_failures": failures,
            "requests_used": attempted,
            "request_budget": self.max_requests_per_cycle,
            "eligible_rows": len(eligible),
            "rejected_rows": len(rejected),
            "rejected_event_ids": rejected,
            "deferred_rows": len(deferred),
            "deferred_event_ids": deferred,
            "min_interval_seconds": self.min_interval_seconds,
        }
