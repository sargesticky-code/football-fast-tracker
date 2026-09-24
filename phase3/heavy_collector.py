"""Phase 3 Layer 6 wiring from Fast Lane state to bounded Heavy Lane collection.

This module consumes already-authorised Fast Lane rows. It never performs identity
matching and never creates HKJC eligibility. Only rows that are live, explicitly
HKJC-authorised, and persistently VERIFIED can become heavy targets.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from phase3.heavy_lane import HeavyLane, HeavyTarget

LIVE_STATUSES = frozenset({"LIVE", "IN_PLAY", "INPLAY", "1H", "2H", "HT", "ET", "PEN"})


def _is_live(row: Mapping[str, Any]) -> bool:
    status = str(row.get("status") or row.get("match_status") or "").strip().upper()
    if status in LIVE_STATUSES:
        return True
    # A parsed live minute is useful only when Fast Lane has not labelled the row terminal.
    terminal = status in {"FT", "FINISHED", "CANCELLED", "POSTPONED", "ABANDONED"}
    minute = row.get("minute")
    return not terminal and isinstance(minute, (int, float)) and not isinstance(minute, bool) and minute >= 0


def heavy_targets_from_fast_state(state: Mapping[str, Any]) -> tuple[list[HeavyTarget], dict[str, Any]]:
    """Build fail-closed heavy targets from current Fast Lane rows.

    No fuzzy matching occurs here. Missing/ambiguous identity or authority evidence
    is rejected and remains visible in diagnostics.
    """
    raw_rows = state.get("rows") or state.get("joined_rows") or []
    rows: Iterable[Mapping[str, Any]] = raw_rows if isinstance(raw_rows, list) else []
    targets: list[HeavyTarget] = []
    rejected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for row in rows:
        if not isinstance(row, Mapping) or not _is_live(row):
            continue
        event_id = str(row.get("hkjc_event_id") or "").strip()
        source = str(row.get("external_source") or row.get("source") or "").strip().lower()
        external_id = str(row.get("external_id") or "").strip()
        identity = str(row.get("identity_status") or "").strip().upper()
        authorised = row.get("hkjc_authorised") is True
        reason = None
        if not event_id or not external_id or not source:
            reason = "IDENTITY_MISSING"
        elif identity != "VERIFIED":
            reason = "IDENTITY_NOT_VERIFIED"
        elif not authorised:
            reason = "HKJC_NOT_AUTHORISED"
        elif (source, external_id) in seen:
            reason = "DUPLICATE_EXTERNAL_ID"
        if reason:
            rejected.append({"hkjc_event_id": event_id, "external_id": external_id, "reason": reason})
            continue
        seen.add((source, external_id))
        targets.append(HeavyTarget(event_id, source, external_id, identity_status="VERIFIED", hkjc_authorised=True))

    return targets, {
        "fast_rows_seen": len(raw_rows) if isinstance(raw_rows, list) else 0,
        "live_candidate_rows": len(targets) + len(rejected),
        "heavy_target_rows": len(targets),
        "heavy_target_rejected_rows": len(rejected),
        "heavy_target_rejections": rejected,
    }


class HeavyCollector:
    """Executable Layer-6 boundary: current Fast state -> bounded heavy collection."""

    def __init__(self, lane: HeavyLane):
        self.lane = lane

    def collect(self, fast_state: Mapping[str, Any], *, now: Any = None) -> dict[str, Any]:
        targets, targeting = heavy_targets_from_fast_state(fast_state)
        result = self.lane.collect(targets, now=now)
        result["targeting"] = targeting
        result["fast_observed_at"] = fast_state.get("observed_at")
        # heavy_observed_at is owned by HeavyLane and intentionally independent.
        return result
