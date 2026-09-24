"""Conservative SofaScore discovery + H2H adapter for Phase 1.

Design goals:
- HKJC remains the canonical fixture identity.
- SofaScore is enrichment only.
- No fuzzy-force matching and no anti-bot bypass logic.
- Persistent verified SofaScore team/event IDs should be stored by the caller
  after a unique fixture match is proven.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import time
import unicodedata
from typing import Any, Iterable

import requests

BASE_URL = "https://api.sofascore.com/api/v1"
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_KICKOFF_TOLERANCE_SECONDS = 20 * 60
DEFAULT_H2H_LIMIT = 5


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def normalize_identity_name(value: Any) -> str:
    """Conservative normalization for exact identity comparisons.

    This removes formatting noise only. It intentionally keeps cohort markers
    such as women, u21, reserve, b, etc. so distinct teams cannot collapse.
    """
    text = unicodedata.normalize("NFKD", _text(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " and ")
    text = re.sub(r"[’'\`´]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = _text(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class FixtureIdentity:
    hkjc_event_id: str
    kickoff: datetime
    home: str
    away: str
    tournament: str = ""


@dataclass(frozen=True)
class SofaEventMatch:
    status: str
    reason: str
    event_id: int | None = None
    home_team_id: int | None = None
    away_team_id: int | None = None
    home_name: str = ""
    away_name: str = ""
    tournament: str = ""
    kickoff_delta_seconds: float | None = None


class SofascoreClient:
    """Small public-endpoint client.

    We deliberately use standard HTTP only. If SofaScore rejects a request,
    the caller gets a normal source failure and can keep last-known-good data.
    """

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
        user_agent: str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://www.sofascore.com",
                "Referer": "https://www.sofascore.com/",
                "User-Agent": user_agent,
                "X-Requested-With": "XMLHttpRequest",
            }
        )

    def _get_json(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 429:
                    raise requests.HTTPError("SofaScore rate limited request", response=response)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("SofaScore response is not an object")
                return payload
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.35)
        assert last_error is not None
        raise last_error

    def scheduled_events(self, date_yyyy_mm_dd: str) -> dict[str, Any]:
        return self._get_json(f"sport/football/scheduled-events/{date_yyyy_mm_dd}")

    def event(self, event_id: int | str) -> dict[str, Any]:
        return self._get_json(f"event/{event_id}")

    def h2h_events(self, event_id: int | str) -> dict[str, Any]:
        return self._get_json(f"event/{event_id}/h2h/events")


def _source_name_set(
    canonical_name: str,
    verified_aliases: dict[str, Iterable[str]] | None,
) -> set[str]:
    names = {normalize_identity_name(canonical_name)}
    if verified_aliases:
        for alias in verified_aliases.get(canonical_name, ()):
            n = normalize_identity_name(alias)
            if n:
                names.add(n)
    return {n for n in names if n}


def _event_kickoff(event: dict[str, Any]) -> datetime | None:
    return parse_timestamp(event.get("startTimestamp") or event.get("start_time"))


def _event_tournament(event: dict[str, Any]) -> str:
    tournament = event.get("tournament") or {}
    unique = tournament.get("uniqueTournament") or {}
    return _text(unique.get("name") or tournament.get("name"))


def match_scheduled_event(
    fixture: FixtureIdentity,
    events_payload: dict[str, Any],
    *,
    verified_aliases: dict[str, Iterable[str]] | None = None,
    kickoff_tolerance_seconds: int = DEFAULT_KICKOFF_TOLERANCE_SECONDS,
) -> SofaEventMatch:
    """Return a unique, identity-safe SofaScore event mapping.

    Matching requires exact normalized home and away names (or pre-verified
    aliases) plus kickoff proximity. If more than one candidate survives, the
    result is AMBIGUOUS instead of guessing.
    """
    events = events_payload.get("events")
    if not isinstance(events, list):
        return SofaEventMatch("SOURCE_ERROR", "scheduled_events_missing")

    home_names = _source_name_set(fixture.home, verified_aliases)
    away_names = _source_name_set(fixture.away, verified_aliases)
    fixture_kickoff = fixture.kickoff.astimezone(timezone.utc)

    candidates: list[tuple[dict[str, Any], float]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        home = event.get("homeTeam") or {}
        away = event.get("awayTeam") or {}
        if normalize_identity_name(home.get("name")) not in home_names:
            continue
        if normalize_identity_name(away.get("name")) not in away_names:
            continue
        kickoff = _event_kickoff(event)
        if kickoff is None:
            continue
        delta = abs((kickoff - fixture_kickoff).total_seconds())
        if delta > kickoff_tolerance_seconds:
            continue
        candidates.append((event, delta))

    if not candidates:
        return SofaEventMatch("UNMAPPED", "no_exact_pair_in_kickoff_window")
    candidates.sort(key=lambda item: item[1])
    best_delta = candidates[0][1]
    tied = [item for item in candidates if abs(item[1] - best_delta) < 1]
    if len(tied) != 1:
        return SofaEventMatch("AMBIGUOUS", "multiple_exact_pair_candidates")

    event, delta = candidates[0]
    home = event.get("homeTeam") or {}
    away = event.get("awayTeam") or {}
    event_id = event.get("id")
    home_id = home.get("id")
    away_id = away.get("id")
    if not isinstance(event_id, int) or not isinstance(home_id, int) or not isinstance(away_id, int):
        return SofaEventMatch("SOURCE_ERROR", "candidate_missing_numeric_ids")

    return SofaEventMatch(
        "VERIFIED",
        "exact_pair_and_kickoff",
        event_id=event_id,
        home_team_id=home_id,
        away_team_id=away_id,
        home_name=_text(home.get("name")),
        away_name=_text(away.get("name")),
        tournament=_event_tournament(event),
        kickoff_delta_seconds=delta,
    )


def _score_pair(event: dict[str, Any]) -> tuple[int, int] | None:
    home_score = event.get("homeScore") or {}
    away_score = event.get("awayScore") or {}
    hv = home_score.get("current")
    av = away_score.get("current")
    if not isinstance(hv, (int, float)) or not isinstance(av, (int, float)):
        return None
    return int(hv), int(av)


def _is_finished(event: dict[str, Any]) -> bool:
    status = event.get("status") or {}
    code = status.get("code")
    status_type = _text(status.get("type")).casefold()
    return code == 100 or status_type in {"finished", "afterpenalties", "afterextratime"}


def normalize_h2h_events(
    payload: dict[str, Any],
    *,
    current_home_team_id: int,
    current_away_team_id: int,
    current_kickoff: datetime | None = None,
    limit: int = DEFAULT_H2H_LIMIT,
) -> list[dict[str, Any]]:
    """Normalize direct meetings into the CURRENT fixture orientation."""
    events = payload.get("events")
    if not isinstance(events, list):
        return []

    cutoff = current_kickoff.astimezone(timezone.utc) if current_kickoff else None
    normalized: list[dict[str, Any]] = []
    wanted = {current_home_team_id, current_away_team_id}

    for event in events:
        if not isinstance(event, dict) or not _is_finished(event):
            continue
        home = event.get("homeTeam") or {}
        away = event.get("awayTeam") or {}
        source_home_id = home.get("id")
        source_away_id = away.get("id")
        if {source_home_id, source_away_id} != wanted:
            continue
        kickoff = _event_kickoff(event)
        if kickoff is None or (cutoff is not None and kickoff >= cutoff):
            continue
        score = _score_pair(event)
        if score is None:
            continue
        source_home_goals, source_away_goals = score
        same_orientation = (
            source_home_id == current_home_team_id
            and source_away_id == current_away_team_id
        )
        current_home_goals = source_home_goals if same_orientation else source_away_goals
        current_away_goals = source_away_goals if same_orientation else source_home_goals
        result = (
            "H"
            if current_home_goals > current_away_goals
            else "A"
            if current_home_goals < current_away_goals
            else "D"
        )
        normalized.append(
            {
                "_kickoff": kickoff,
                "source_event_id": event.get("id"),
                "kickoff_utc": kickoff.isoformat(),
                "tournament": _event_tournament(event),
                "home": _text(home.get("name")),
                "away": _text(away.get("name")),
                "home_team_id": source_home_id,
                "away_team_id": source_away_id,
                "home_goals": source_home_goals,
                "away_goals": source_away_goals,
                "current_home_goals": current_home_goals,
                "current_away_goals": current_away_goals,
                "result": result,
            }
        )

    normalized.sort(key=lambda row: row["_kickoff"], reverse=True)
    recent = normalized[: max(0, limit)]
    for row in recent:
        row.pop("_kickoff", None)
    return recent


def summarize_h2h(meetings: list[dict[str, Any]]) -> dict[str, Any]:
    games = len(meetings)
    home_wins = sum(row.get("result") == "H" for row in meetings)
    draws = sum(row.get("result") == "D" for row in meetings)
    away_wins = sum(row.get("result") == "A" for row in meetings)
    home_goals = sum(int(row.get("current_home_goals") or 0) for row in meetings)
    away_goals = sum(int(row.get("current_away_goals") or 0) for row in meetings)
    return {
        "h2h_games": games,
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": away_wins,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "avg_total_goals": ((home_goals + away_goals) / games) if games else None,
        "last5": "".join(_text(row.get("result")) for row in meetings),
        "meetings": meetings,
        "source": "SOFASCORE",
        "quality": "H2H_OK" if games else "NO_HISTORY",
    }
