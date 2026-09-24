"""Phase 1 FotMob fixture discovery + direct H2H adapter.

HKJC remains canonical. FotMob may enrich H2H only after a unique fixture
mapping based on verified/static team aliases and kickoff proximity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Iterable

import requests

BASE_URL = "https://www.fotmob.com/api"
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_KICKOFF_TOLERANCE_SECONDS = 20 * 60
DEFAULT_H2H_LIMIT = 5


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def normalize_name(value: Any) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", text(value))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold().replace("&", " and ")
    s = re.sub(r"[’'\`´]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        n=float(value)
        if n > 10_000_000_000:
            n /= 1000
        try:
            return datetime.fromtimestamp(n, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    s=text(value)
    if not s:
        return None
    try:
        dt=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Fixture:
    hkjc_event_id: str
    kickoff: datetime
    home: str
    away: str
    tournament: str = ""


@dataclass(frozen=True)
class MatchResult:
    status: str
    reason: str
    match_id: int | None = None
    home_team_id: int | None = None
    away_team_id: int | None = None
    home_name: str = ""
    away_name: str = ""
    league: str = ""
    kickoff_delta_seconds: float | None = None


class FotMobClient:
    def __init__(self, *, timeout: float=DEFAULT_TIMEOUT_SECONDS, session: requests.Session | None=None):
        self.timeout=timeout
        self.session=session or requests.Session()
        self.session.headers.update({
            "Accept":"application/json, */*",
            "Accept-Language":"en-US,en;q=0.9",
            "Referer":"https://www.fotmob.com/",
            "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
        })

    def _get(self, path: str, params: dict[str,Any]) -> dict[str,Any]:
        response=self.session.get(f"{BASE_URL}/{path.lstrip('/')}", params=params, timeout=self.timeout)
        response.raise_for_status()
        payload=response.json()
        if not isinstance(payload,dict):
            raise ValueError("FotMob payload is not an object")
        return payload

    def matches(self, date_yyyymmdd: str) -> dict[str,Any]:
        return self._get("matches", {"date":date_yyyymmdd})

    def match_details(self, match_id: int | str) -> dict[str,Any]:
        return self._get("matchDetails", {"matchId":str(match_id)})


def flatten_matches(payload: dict[str,Any]) -> list[dict[str,Any]]:
    out=[]
    leagues=payload.get("leagues")
    if not isinstance(leagues,list):
        return out
    for league in leagues:
        if not isinstance(league,dict):
            continue
        league_name=text(league.get("name"))
        for match in league.get("matches") or []:
            if isinstance(match,dict):
                row=dict(match)
                row["_league_name"]=league_name
                out.append(row)
    return out


def _name_set(canonical: str, aliases: dict[str,Iterable[str]] | None) -> set[str]:
    values={normalize_name(canonical)}
    for alias in (aliases or {}).get(canonical,()):
        n=normalize_name(alias)
        if n:
            values.add(n)
    return {x for x in values if x}


def _match_kickoff(row: dict[str,Any]) -> datetime | None:
    status=row.get("status") if isinstance(row.get("status"),dict) else {}
    return parse_datetime(status.get("utcTime") or row.get("timeTS") or row.get("utcTime"))


def match_fixture(
    fixture: Fixture,
    boards: Iterable[dict[str,Any]],
    *,
    aliases: dict[str,Iterable[str]] | None=None,
    kickoff_tolerance_seconds: int=DEFAULT_KICKOFF_TOLERANCE_SECONDS,
) -> MatchResult:
    home_names=_name_set(fixture.home,aliases)
    away_names=_name_set(fixture.away,aliases)
    kickoff=fixture.kickoff.astimezone(timezone.utc)
    candidates=[]
    for board in boards:
        for row in flatten_matches(board):
            home=row.get("home") if isinstance(row.get("home"),dict) else {}
            away=row.get("away") if isinstance(row.get("away"),dict) else {}
            if normalize_name(home.get("name")) not in home_names:
                continue
            if normalize_name(away.get("name")) not in away_names:
                continue
            when=_match_kickoff(row)
            if when is None:
                continue
            delta=abs((when-kickoff).total_seconds())
            if delta <= kickoff_tolerance_seconds:
                candidates.append((row,delta))
    if not candidates:
        return MatchResult("UNMAPPED","no_exact_pair_in_kickoff_window")
    # The same FotMob match can appear on both UTC/HKT date-board requests.
    # De-duplicate by stable match id before ambiguity checks.
    deduped={}
    for row,delta in candidates:
        key=text(row.get("id"))
        prior=deduped.get(key)
        if prior is None or delta < prior[1]:
            deduped[key]=(row,delta)
    candidates=list(deduped.values())
    candidates.sort(key=lambda x:x[1])
    best_delta=candidates[0][1]
    best=[x for x in candidates if abs(x[1]-best_delta)<1]
    if len(best)!=1:
        return MatchResult("AMBIGUOUS","multiple_exact_pair_candidates")
    row,delta=best[0]
    home=row.get("home") or {}; away=row.get("away") or {}
    try:
        mid=int(row.get("id")); hid=int(home.get("id")); aid=int(away.get("id"))
    except (TypeError,ValueError):
        return MatchResult("SOURCE_ERROR","candidate_missing_numeric_ids")
    return MatchResult(
        "VERIFIED","exact_pair_and_kickoff",
        match_id=mid,home_team_id=hid,away_team_id=aid,
        home_name=text(home.get("name")),away_name=text(away.get("name")),
        league=text(row.get("_league_name")),kickoff_delta_seconds=delta,
    )


def _score(score_str: Any) -> tuple[int,int] | None:
    m=re.search(r"(\d+)\s*[-–:]\s*(\d+)",text(score_str))
    return (int(m.group(1)),int(m.group(2))) if m else None


def _h2h_root(payload: dict[str,Any]) -> dict[str,Any]:
    content=payload.get("content") if isinstance(payload.get("content"),dict) else {}
    direct=content.get("h2h")
    if isinstance(direct,dict):
        return direct
    facts=content.get("matchFacts") if isinstance(content.get("matchFacts"),dict) else {}
    return facts.get("h2h") if isinstance(facts.get("h2h"),dict) else {}


def normalize_h2h(
    payload: dict[str,Any],
    *,
    current_home_team_id: int,
    current_away_team_id: int,
    limit: int=DEFAULT_H2H_LIMIT,
) -> list[dict[str,Any]]:
    h2h=_h2h_root(payload)
    rows=h2h.get("matches")
    if not isinstance(rows,list):
        return []
    wanted={str(current_home_team_id),str(current_away_team_id)}
    out=[]
    for row in rows:
        if not isinstance(row,dict):
            continue
        home=row.get("home") if isinstance(row.get("home"),dict) else {}
        away=row.get("away") if isinstance(row.get("away"),dict) else {}
        if {text(home.get("id")),text(away.get("id"))} != wanted:
            continue
        status=row.get("status") if isinstance(row.get("status"),dict) else {}
        if not bool(status.get("finished")):
            continue
        score=_score(status.get("scoreStr"))
        if score is None:
            continue
        hg,ag=score
        same=text(home.get("id"))==str(current_home_team_id)
        chg=hg if same else ag
        cag=ag if same else hg
        result="H" if chg>cag else ("A" if chg<cag else "D")
        match_url=text(row.get("matchUrl"))
        id_match=re.search(r"/livescores/(\d+)/",match_url)
        out.append({
            "source_event_id": int(id_match.group(1)) if id_match else None,
            "date": text(status.get("startDateStr") or row.get("time")),
            "tournament": text((row.get("league") or {}).get("name")) if isinstance(row.get("league"),dict) else "",
            "home": text(home.get("name")),
            "away": text(away.get("name")),
            "home_team_id": text(home.get("id")),
            "away_team_id": text(away.get("id")),
            "home_goals": hg,
            "away_goals": ag,
            "current_home_goals": chg,
            "current_away_goals": cag,
            "result": result,
        })
        if len(out)>=max(0,limit):
            break
    return out


def summarize(meetings: list[dict[str,Any]]) -> dict[str,Any]:
    n=len(meetings)
    hw=sum(x.get("result")=="H" for x in meetings)
    d=sum(x.get("result")=="D" for x in meetings)
    aw=sum(x.get("result")=="A" for x in meetings)
    hg=sum(int(x.get("current_home_goals") or 0) for x in meetings)
    ag=sum(int(x.get("current_away_goals") or 0) for x in meetings)
    return {
        "h2h_games":n,"home_wins":hw,"draws":d,"away_wins":aw,
        "home_goals":hg,"away_goals":ag,
        "avg_total_goals":((hg+ag)/n) if n else None,
        "last5":"".join(text(x.get("result")) for x in meetings),
        "meetings":meetings,
        "source":"FOTMOB",
        "quality":"H2H_OK" if n else "NO_HISTORY",
    }
