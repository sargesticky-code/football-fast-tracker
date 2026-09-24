"""SofaScore lightweight live-board adapter for Phase 3 shadow benchmarking.

Shadow only: this module never changes HKJC eligibility, never fuzzy-rematches,
and never promotes SofaScore to production primary.  Persistent VERIFIED
mappings are supplied by the caller as {sofascore_event_id: hkjc_match_id}.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

LIVE_STATUSES = {"inprogress", "live", "1st", "2nd", "halftime", "extra"}


def _score(side: Mapping[str, Any] | None) -> int | None:
    if not side:
        return None
    value = side.get("current")
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _source_updated_at(event: Mapping[str, Any]) -> str | None:
    # SofaScore live events commonly expose changes.changeTimestamp; keep it
    # source-derived and optional rather than inventing freshness.
    changes = event.get("changes") or {}
    ts = changes.get("changeTimestamp")
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def normalize_live_board(payload: Mapping[str, Any], verified_ids: Mapping[str, str]) -> dict[str, Any]:
    """Normalize one multi-match live board using persistent verified IDs only."""
    rows: list[dict[str, Any]] = []
    unmapped = 0
    collisions = 0
    seen_hkjc: set[str] = set()
    source_times: list[str] = []
    for event in payload.get("events") or []:
        external_id = str(event.get("id") or "")
        hkjc_id = verified_ids.get(external_id)
        if not hkjc_id:
            unmapped += 1
            continue
        if hkjc_id in seen_hkjc:
            collisions += 1
            continue
        seen_hkjc.add(hkjc_id)
        status_obj = event.get("status") or {}
        status_type = str(status_obj.get("type") or "").lower()
        status_desc = str(status_obj.get("description") or "").lower()
        is_live = status_type in LIVE_STATUSES or status_desc in LIVE_STATUSES
        home = event.get("homeScore") or {}
        away = event.get("awayScore") or {}
        updated = _source_updated_at(event)
        if updated:
            source_times.append(updated)
        rows.append({
            "hkjc_match_id": hkjc_id,
            "external_id": external_id,
            "identity_status": "VERIFIED",
            "status": "LIVE" if is_live else str(status_obj.get("type") or "UNKNOWN").upper(),
            "home_score": _score(home),
            "away_score": _score(away),
            "source_updated_at": updated,
        })
    return {
        "rows": rows,
        "unmapped_rows": unmapped,
        "collision_rows": collisions,
        "source_updated_at": max(source_times) if source_times else None,
        "board_rows": len(payload.get("events") or []),
    }
