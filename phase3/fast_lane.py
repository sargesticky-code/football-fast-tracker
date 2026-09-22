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
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        value = match.group(0) if match else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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
    """Return non-negative board age; malformed/future timestamps fail closed."""
    observed = _parse_time(observed_at)
    current = _parse_time(now) if now is not None else datetime.now(timezone.utc)
    if observed is None or current is None:
        return None
    age = (current - observed).total_seconds()
    return age if age >= 0 else None


def _is_live_row(row: dict[str, Any]) -> bool:
    """Require plausible genuine minute and complete score for live evidence."""
    status = str(row.get("status") or "").strip().upper()
    terminal = {"FT", "FULL TIME", "FULL-TIME", "AET", "PEN", "CANCELLED", "CANCELED", "POSTPONED", "ABANDONED"}
    if status in terminal:
        return False
    minute = _int_or_none(row.get("minute"))
    home_score = _int_or_none(row.get("home_score"))
    away_score = _int_or_none(row.get("away_score"))
    # A status label alone is not live evidence. Minute zero can occur before a
    # match has actually begun, and impossible negative/very large values must
    # fail closed rather than creating a false FRESH_LIVE exit observation.
    return (
        minute is not None and 1 <= minute <= 130
        and home_score is not None and home_score >= 0
        and away_score is not None and away_score >= 0
    )


def fast_lane_health(joined_rows: Iterable[dict[str, Any]], observed_at: Any, *, now: Any = None,
                     request_failures: int = 0, max_age_seconds: float = 15.0) -> dict[str, Any]:
    """Summarise Layer 3 heartbeat freshness without fabricating live state.

    Request failures and stale/malformed timestamps fail closed. FRESH_LIVE
    requires a plausible real source minute plus complete non-negative score;
    partial/status-only rows cannot satisfy the Layer-3 exit criterion.
    """
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
    """Index only VERIFIED identities; candidates/conflicts fail closed."""
    out = {}
    for row in registry_rows:
        if not isinstance(row, dict) or row.get("status") != "VERIFIED":
            continue
        source = str(row.get("source") or "").upper()
        external_id = str(row.get("external_id") or row.get("source_match_id") or "")
        event_id = str(row.get("hkjc_event_id") or "")
        if source and external_id and event_id:
            out[(source, external_id)] = row
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
    if isinstance(score, str) and "-" in score:
        left, right = score.split("-", 1)
        return _int_or_none(left), _int_or_none(right)
    return _team_score(match.get("home")), _team_score(match.get("away"))


def normalize_fotmob_board(payload: dict[str, Any], observed_at: str | None = None) -> list[dict[str, Any]]:
    """Normalize FotMob /api/data/matches board into lightweight rows."""
    observed_at = observed_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    matches = []
    top_matches = payload.get("matches") if isinstance(payload, dict) else None
    if isinstance(top_matches, list): matches.extend(top_matches)
    leagues = payload.get("leagues") if isinstance(payload, dict) else None
    if isinstance(leagues, list):
        for league in leagues:
            if not isinstance(league, dict): continue
            league_matches = league.get("matches")
            if isinstance(league_matches, list): matches.extend(league_matches)
    rows = []
    for match in matches:
        if not isinstance(match, dict): continue
        mid = match.get("id")
        if mid is None: continue
        status = match.get("status") or {}
        if not isinstance(status, dict): status = {}
        live_time = status.get("liveTime")
        if isinstance(live_time, dict): live_time = live_time.get("short") or live_time.get("long")
        home_score, away_score = _score(match, status)
        rows.append({"source":"FOTMOB","external_id":str(mid),"status":_status_text(status),
                     "minute":_int_or_none(live_time),"home_score":home_score,"away_score":away_score,
                     "observed_at":observed_at})
    return rows


def join_verified_fast_rows(registry_rows: Iterable[dict[str, Any]], board_rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Join heartbeat rows to persistent identities without fuzzy rematching."""
    idx = verified_index(registry_rows); joined, unmapped = [], []
    for row in board_rows:
        if not isinstance(row, dict): continue
        key = (str(row.get("source") or "").upper(), str(row.get("external_id") or ""))
        identity = idx.get(key)
        if not identity:
            unmapped.append(dict(row)); continue
        joined.append(FastRow(hkjc_event_id=str(identity["hkjc_event_id"]), external_source=key[0], external_id=key[1],
            status=row.get("status"), minute=_int_or_none(row.get("minute")), home_score=_int_or_none(row.get("home_score")),
            away_score=_int_or_none(row.get("away_score")), observed_at=str(row.get("observed_at") or "")).as_dict())
    return joined, unmapped
