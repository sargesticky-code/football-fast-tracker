"""Phase 3 Layer 3 lightweight live heartbeat.

Consumes only VERIFIED Layer 2 external identities. External data enriches an
HKJC-authorised match; it never creates HKJC eligibility.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class FastRow:
    hkjc_event_id: str
    external_source: str
    external_id: str
    status: str | None
    minute: int | None
    home_score: int | None
    away_score: int | None
    observed_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _int_or_none(value: Any) -> int | None:
    # bool is an int subclass in Python. Treating True/False as 1/0 can
    # fabricate a plausible football score or request-failure count.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"[+-]?\d+", text):
            return None
        value = text
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _minute_or_none(value: Any) -> int | None:
    """Parse an elapsed football minute without silently dropping stoppage time."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    match = re.fullmatch(r"(\d{1,3})(?:\s*\+\s*(\d{1,2}))?\s*['’]?", text)
    if not match:
        return None
    base = int(match.group(1))
    added = int(match.group(2) or 0)
    return base + added


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fast_snapshot_age_seconds(observed_at: Any, now: Any = None) -> float | None:
    observed = _parse_time(observed_at)
    current = _parse_time(now) if now is not None else datetime.now(timezone.utc)
    if observed is None or current is None:
        return None
    age = (current - observed).total_seconds()
    return age if age >= 0 else None


def _is_live_row(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").strip().upper()
    live_statuses = {"1ST", "2ND", "LIVE", "ET", "EXTRA TIME", "EXTRA-TIME"}
    if status not in live_statuses:
        return False
    minute = _minute_or_none(row.get("minute"))
    home_score = _int_or_none(row.get("home_score"))
    away_score = _int_or_none(row.get("away_score"))
    return (minute is not None and 1 <= minute <= 130
            and home_score is not None and home_score >= 0
            and away_score is not None and away_score >= 0)


def fast_lane_health(joined_rows: Iterable[dict[str, Any]], observed_at: Any, *, now: Any = None,
                     request_failures: int = 0, max_age_seconds: float = 15.0) -> dict[str, Any]:
    rows = [row for row in joined_rows if isinstance(row, dict)]
    age = fast_snapshot_age_seconds(observed_at, now)
    live_rows = [row for row in rows if _is_live_row(row)]
    failures = max(0, _int_or_none(request_failures) or 0)
    if failures:
        health = "REQUEST_FAILED"
    elif age is None:
        health = "NO_FAST_SNAPSHOT"
    elif age > max_age_seconds:
        health = "STALE_FAST_SNAPSHOT"
    elif live_rows:
        health = "FRESH_LIVE"
    elif rows:
        health = "FRESH_PARTIAL_OR_TERMINAL"
    else:
        health = "FRESH_NO_MAPPED_ROWS"
    return {"health": health, "snapshot_age_seconds": age, "request_failures": failures,
            "mapped_rows": len(rows), "live_rows": len(live_rows)}


def verified_index(registry_rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    collisions: set[tuple[str, str]] = set()
    for row in registry_rows:
        if not isinstance(row, dict) or row.get("status") != "VERIFIED":
            continue
        source = str(row.get("source") or "").upper()
        external_id = str(row.get("external_id") or row.get("source_match_id") or "")
        event_id = str(row.get("hkjc_event_id") or "")
        if not (source and external_id and event_id):
            continue
        key = (source, external_id)
        existing = out.get(key)
        if existing is not None and str(existing.get("hkjc_event_id") or "") != event_id:
            collisions.add(key)
            out.pop(key, None)
            continue
        if key not in collisions:
            out[key] = row
    return out


def _status_text(status: dict[str, Any]) -> str | None:
    reason = status.get("reason")
    if isinstance(reason, dict):
        return reason.get("short") or reason.get("long")
    return status.get("status") or (str(reason) if reason is not None else None)


def _team_score(value: Any) -> int | None:
    return _int_or_none(value.get("score")) if isinstance(value, dict) else None


def _score(match: dict[str, Any], status: dict[str, Any]) -> tuple[int | None, int | None]:
    score = status.get("scoreStr") or match.get("scoreStr") or ""
    if isinstance(score, str):
        pair = re.fullmatch(r"\s*([+-]?\d+)\s*-\s*([+-]?\d+)\s*", score)
        if pair:
            return _int_or_none(pair.group(1)), _int_or_none(pair.group(2))
    return _team_score(match.get("home")), _team_score(match.get("away"))


def normalize_fotmob_board(payload: dict[str, Any], observed_at: str | None = None) -> list[dict[str, Any]]:
    observed_at = observed_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    matches = []
    top_matches = payload.get("matches") if isinstance(payload, dict) else None
    if isinstance(top_matches, list):
        matches.extend(top_matches)
    leagues = payload.get("leagues") if isinstance(payload, dict) else None
    if isinstance(leagues, list):
        for league in leagues:
            if not isinstance(league, dict):
                continue
            league_matches = league.get("matches")
            if isinstance(league_matches, list):
                matches.extend(league_matches)
    rows = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        mid = match.get("id")
        if mid is None:
            continue
        status = match.get("status") or {}
        if not isinstance(status, dict):
            status = {}
        live_time = status.get("liveTime")
        if isinstance(live_time, dict):
            live_time = live_time.get("short") or live_time.get("long")
        home_score, away_score = _score(match, status)
        rows.append({"source": "FOTMOB", "external_id": str(mid), "status": _status_text(status),
                     "minute": _minute_or_none(live_time), "home_score": home_score, "away_score": away_score,
                     "observed_at": observed_at})
    return rows


def _board_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    """Fields that must agree when a board repeats the same external match ID."""
    return (str(row.get("status") or "").strip().upper(), _minute_or_none(row.get("minute")),
            _int_or_none(row.get("home_score")), _int_or_none(row.get("away_score")))


def join_verified_fast_rows(registry_rows: Iterable[dict[str, Any]], board_rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Join heartbeat rows without fuzzy rematching or ambiguous duplicate evidence.

    FotMob can expose the same match in more than one board container. Identical
    duplicates are deduplicated. If duplicate rows disagree on live state, the
    external ID is quarantined for that snapshot rather than selecting one by
    iteration order and potentially fabricating a live heartbeat.
    """
    idx = verified_index(registry_rows)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in board_rows:
        if not isinstance(row, dict):
            continue
        key = (str(row.get("source") or "").upper(), str(row.get("external_id") or ""))
        grouped.setdefault(key, []).append(row)

    joined, unmapped = [], []
    for key, candidates in grouped.items():
        identity = idx.get(key)
        if not identity:
            unmapped.extend(dict(row) for row in candidates)
            continue
        signatures = {_board_signature(row) for row in candidates}
        if len(signatures) != 1:
            unmapped.extend(dict(row) for row in candidates)
            continue
        row = candidates[0]
        joined.append(FastRow(hkjc_event_id=str(identity["hkjc_event_id"]), external_source=key[0], external_id=key[1],
            status=row.get("status"), minute=_minute_or_none(row.get("minute")), home_score=_int_or_none(row.get("home_score")),
            away_score=_int_or_none(row.get("away_score")), observed_at=str(row.get("observed_at") or "")).as_dict())
    return joined, unmapped