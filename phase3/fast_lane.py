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
    """Normalize FotMob /api/data/matches board into lightweight rows.

    The public board has changed container shapes over time. Ignore malformed
    containers/rows rather than allowing one unrelated league to erase the
    whole heartbeat cycle.
    """
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
        rows.append({
            "source": "FOTMOB",
            "external_id": str(mid),
            "status": _status_text(status),
            "minute": _int_or_none(live_time),
            "home_score": home_score,
            "away_score": away_score,
            "observed_at": observed_at,
        })
    return rows


def join_verified_fast_rows(registry_rows: Iterable[dict[str, Any]], board_rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Join heartbeat rows to persistent identities without fuzzy rematching."""
    idx = verified_index(registry_rows)
    joined, unmapped = [], []
    for row in board_rows:
        if not isinstance(row, dict):
            continue
        key = (str(row.get("source") or "").upper(), str(row.get("external_id") or ""))
        identity = idx.get(key)
        if not identity:
            unmapped.append(dict(row))
            continue
        joined.append(FastRow(
            hkjc_event_id=str(identity["hkjc_event_id"]),
            external_source=key[0], external_id=key[1],
            status=row.get("status"), minute=_int_or_none(row.get("minute")),
            home_score=_int_or_none(row.get("home_score")), away_score=_int_or_none(row.get("away_score")),
            observed_at=str(row.get("observed_at") or ""),
        ).as_dict())
    return joined, unmapped
