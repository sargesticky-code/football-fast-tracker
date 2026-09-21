"""Phase 3 Layer 1: HKJC live-authority contract.

HKJC alone decides whether a fixture is eligible for Phase 3 live intelligence.
External score/stat providers may enrich an eligible HKJC fixture later, but
must never create eligibility.

This module is deliberately pure: callers provide an HKJC snapshot plus the
snapshot fetch time. That keeps authority semantics testable and independent
from capture transport/polling.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

DEFAULT_STALE_AFTER_SECONDS = 300

LIVE_MATCH_STATUSES = {
    "FIRSTHALF",
    "SECONDHALF",
    "INPLAY",
    "LIVE",
    "FIRSTHALFOVERTIME",
    "SECONDHALFOVERTIME",
    "EXTRATIME",
    "PENALTYSHOOTOUT",
}
SELLING_STATUS = "SELLINGSTARTED"


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _upper(value: Any) -> str:
    return _clean(value).upper().replace(" ", "")


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        raw = _clean(value)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _match_status(row: Mapping[str, Any]) -> str:
    return _upper(
        row.get("match_status")
        or row.get("matchStatus")
        or row.get("status")
    )


def _selling_status(row: Mapping[str, Any]) -> str:
    direct = (
        row.get("selling_status")
        or row.get("sellingStatus")
        or row.get("pool_status")
        or row.get("poolStatus")
    )
    if direct:
        return _upper(direct)

    had = row.get("HAD")
    if isinstance(had, Mapping):
        return _upper(had.get("status"))
    return ""


def _event_id(row: Mapping[str, Any]) -> str:
    return _clean(
        row.get("hkjc_event_id")
        or row.get("frontEndId")
        or row.get("event_id")
    )


def _match_id(row: Mapping[str, Any]) -> str:
    return _clean(
        row.get("match_id")
        or row.get("matchId")
        or row.get("id")
    )


@dataclass(frozen=True)
class AuthoritySnapshot:
    health: str
    source_fetched_at: str | None
    snapshot_age_seconds: float | None
    source_rows: int
    eligible_rows: int
    stale_rows: int
    identity_gap_rows: int
    not_selling_rows: int
    not_live_rows: int
    authority_usable: bool
    rows: tuple[dict[str, Any], ...]


def evaluate_authority(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_fetched_at: Any,
    now: datetime | None = None,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> AuthoritySnapshot:
    """Evaluate one HKJC snapshot and fail closed when freshness/identity is weak."""
    raw_rows = [dict(row) for row in rows]
    fetched = _parse_timestamp(source_fetched_at)
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if fetched is None:
        age = None
        globally_stale = True
        health = "NO_SNAPSHOT"
    else:
        age = max(0.0, (now_utc - fetched).total_seconds())
        globally_stale = age > stale_after_seconds
        health = "STALE_AUTHORITY" if globally_stale else ""

    evaluated: list[dict[str, Any]] = []
    stale_rows = 0
    identity_gap_rows = 0
    not_selling_rows = 0
    not_live_rows = 0
    eligible_rows = 0

    for row in raw_rows:
        event_id = _event_id(row)
        match_id = _match_id(row)
        match_status = _match_status(row)
        selling_status = _selling_status(row)

        identity_ok = bool(event_id and match_id)
        selling_ok = selling_status == SELLING_STATUS
        live_ok = match_status in LIVE_MATCH_STATUSES

        if globally_stale:
            eligible = False
            reason = health
            stale_rows += 1
        elif not identity_ok:
            eligible = False
            reason = "IDENTITY_GAP"
            identity_gap_rows += 1
        elif not selling_ok:
            eligible = False
            reason = "NOT_SELLING"
            not_selling_rows += 1
        elif not live_ok:
            eligible = False
            reason = "NOT_LIVE"
            not_live_rows += 1
        else:
            eligible = True
            reason = "ELIGIBLE"
            eligible_rows += 1

        evaluated.append({
            **row,
            "phase3_hkjc_event_id": event_id,
            "phase3_hkjc_match_id": match_id,
            "phase3_match_status": match_status,
            "phase3_selling_status": selling_status,
            "phase3_eligible": eligible,
            "phase3_authority_reason": reason,
        })

    if not health:
        if identity_gap_rows:
            health = "IDENTITY_GAP"
        elif eligible_rows:
            health = "FRESH_ELIGIBLE"
        else:
            health = "FRESH_NO_LIVE_ROWS"

    source_iso = fetched.isoformat() if fetched else None
    authority_usable = fetched is not None and not globally_stale and identity_gap_rows == 0

    return AuthoritySnapshot(
        health=health,
        source_fetched_at=source_iso,
        snapshot_age_seconds=age,
        source_rows=len(raw_rows),
        eligible_rows=eligible_rows,
        stale_rows=stale_rows,
        identity_gap_rows=identity_gap_rows,
        not_selling_rows=not_selling_rows,
        not_live_rows=not_live_rows,
        authority_usable=authority_usable,
        rows=tuple(evaluated),
    )
