"""Low-request pre-match context collector for Fast Tracker.

Purpose:
- match current HKJC fixtures to FotMob scheduled matches
- capture FotMob match/team IDs for later player enrichment
- refresh probable/confirmed lineups close to kickoff
- cache manager identity at team level
- preserve last-good context when an upstream source is temporarily blocked

This is context collection, not a betting model. The scenario engine consumes the
result later.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
HKJC = ROOT / "data" / "hkjc_current.csv"
OUT = ROOT / "data" / "prematch_context_current.csv"
PLAYERS = ROOT / "data" / "prematch_players_current.csv"
MANAGERS = ROOT / "data" / "team_manager_registry.csv"
SQUADS = ROOT / "data" / "team_squad_registry.csv"
STYLES = ROOT / "data" / "team_style_registry.csv"

HKT = ZoneInfo("Asia/Hong_Kong")
FOTMOB = os.getenv("FOTMOB_BASE_URL", "https://www.fotmob.com/api").rstrip("/")
SOFASCORE = os.getenv("SOFASCORE_BASE_URL", "https://www.sofascore.com/api/v1").rstrip("/")
LOOKAHEAD_HOURS = max(6, int(os.getenv("PREMATCH_LOOKAHEAD_HOURS", "36")))
DETAIL_WINDOW_MINUTES = max(30, int(os.getenv("PREMATCH_DETAIL_WINDOW_MINUTES", "180")))
MAX_DETAIL_CALLS = max(0, int(os.getenv("PREMATCH_MAX_DETAIL_CALLS", "6")))
MAX_TEAM_CALLS = max(0, int(os.getenv("PREMATCH_MAX_TEAM_CALLS", "6")))
MAX_SOFASCORE_LINEUP_CALLS = max(0, int(os.getenv("PREMATCH_MAX_SOFASCORE_LINEUP_CALLS", "4")))
TEAM_REFRESH_DAYS = max(1, int(os.getenv("PREMATCH_TEAM_REFRESH_DAYS", "14")))
REQUEST_SLEEP = max(0.0, float(os.getenv("PREMATCH_REQUEST_SLEEP", "0.35")))

CONTEXT_COLUMNS = [
    "fetched_at_hkt", "hkjc_event_id", "kickoff_hkt", "league",
    "home", "away", "fotmob_match_id", "fotmob_league_id",
    "fotmob_home_id", "fotmob_away_id", "match_quality",
    "home_manager", "away_manager", "home_formation", "away_formation",
    "lineup_status", "home_lineup_count", "away_lineup_count",
    "detail_fetched_at_hkt", "quality", "notes",
]

PLAYER_COLUMNS = [
    "fetched_at_hkt", "hkjc_event_id", "side", "team_id", "team",
    "formation", "player_id", "player_name", "position", "shirt_number",
    "starter", "lineup_status", "source",
]

MANAGER_COLUMNS = [
    "team_id", "team_name", "manager_id", "manager_name", "manager_start_date",
    "fetched_at_hkt", "quality", "source",
]

SQUAD_COLUMNS = [
    "team_id", "team_name", "player_id", "player_name",
    "position_group", "fetched_at_hkt", "source",
]

STYLE_COLUMNS = [
    "team_id", "team_name", "manager_id", "manager_name",
    "manager_start_date", "season", "average_possession", "goals_per_match",
    "expected_goals", "xg_conceded", "shots_on_target_per_match",
    "big_chances_created", "possession_won_final_3rd",
    "accurate_passes_per_match", "successful_tackles_per_match",
    "interceptions_per_match", "selected_stats_json",
    "fetched_at_hkt", "quality", "source",
]


def headers():
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.fotmob.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }


def clean(v) -> str:
    return "" if v is None else str(v).strip()


def norm(v) -> str:
    s = unicodedata.normalize("NFKD", clean(v))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).casefold()
    s = s.replace("&", " and ")
    s = re.sub(r"['’\x60]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(fc|cf|sc|afc|club|football|soccer)\b", " ", s)
    return " ".join(s.split())


def sim(a, b) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if min(len(a), len(b)) >= 5 and (a in b or b in a):
        return 0.94
    return SequenceMatcher(None, a, b).ratio()


def parse_dt(v):
    s = clean(v)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HKT)
    return dt.astimezone(HKT)


def read_csv(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in columns})
    tmp.replace(path)


def get_json(session: requests.Session, endpoint: str, params=None):
    r = session.get(
        FOTMOB + endpoint,
        params=params,
        headers=headers(),
        timeout=12,
    )
    r.raise_for_status()
    return r.json()


def sofascore_headers():
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.sofascore.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }


def sofa_json(session: requests.Session, endpoint: str):
    r = session.get(
        SOFASCORE + endpoint,
        headers=sofascore_headers(),
        timeout=12,
    )
    r.raise_for_status()
    return r.json()


def current_targets(now):
    rows = read_csv(HKJC)
    out = []
    upper = now + timedelta(hours=LOOKAHEAD_HOURS)
    lower = now - timedelta(minutes=15)
    for r in rows:
        if clean(r.get("selling")).lower() not in ("1", "true", "yes"):
            continue
        if not all(clean(r.get(k)) for k in ("had_home", "had_draw", "had_away")):
            continue
        kick = parse_dt(r.get("kickoff_hkt"))
        if kick is None or not (lower <= kick <= upper):
            continue
        out.append({
            "hkjc_event_id": clean(r.get("hkjc_event_id")),
            "kickoff": kick,
            "kickoff_hkt": kick.isoformat(timespec="minutes"),
            "league": clean(r.get("tournament")),
            "home": clean(r.get("home_en")),
            "away": clean(r.get("away_en")),
        })
    out.sort(key=lambda x: (x["kickoff"], x["hkjc_event_id"]))
    return out


def fotmob_match_board(session, dates):
    out = []
    for day in sorted(dates):
        payload = get_json(
            session,
            "/data/matches",
            params={"date": day, "timezone": "Asia/Hong_Kong", "ccode3": "HKG"},
        )
        for lg in payload.get("leagues") or []:
            league_id = clean(lg.get("primaryId") or lg.get("id"))
            for m in lg.get("matches") or []:
                home = m.get("home") or {}
                away = m.get("away") or {}
                st = m.get("status") or {}
                kick = parse_dt(st.get("utcTime") or m.get("utcTime"))
                if not kick:
                    continue
                out.append({
                    "match_id": clean(m.get("id")),
                    "league_id": clean(m.get("leagueId") or league_id),
                    "kickoff": kick,
                    "home_id": clean(home.get("id")),
                    "away_id": clean(away.get("id")),
                    "home": clean(home.get("name")),
                    "away": clean(away.get("name")),
                })
        if REQUEST_SLEEP:
            time.sleep(REQUEST_SLEEP)
    return out


def sofascore_board(session, dates):
    out = []
    for day in sorted(dates):
        payload = sofa_json(session, f"/sport/football/scheduled-events/{day}")
        for event in payload.get("events") or []:
            home = event.get("homeTeam") or {}
            away = event.get("awayTeam") or {}
            kick = None
            try:
                ts = event.get("startTimestamp")
                if ts:
                    kick = datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(HKT)
            except Exception:
                kick = None
            if not kick:
                continue
            out.append({
                "match_id": clean(event.get("id")),
                "league_id": clean(((event.get("tournament") or {}).get("uniqueTournament") or {}).get("id")),
                "kickoff": kick,
                "home_id": clean(home.get("id")),
                "away_id": clean(away.get("id")),
                "home": clean(home.get("name") or home.get("shortName")),
                "away": clean(away.get("name") or away.get("shortName")),
            })
        if REQUEST_SLEEP:
            time.sleep(REQUEST_SLEEP)
    return out


def match_fixture(target, board):
    candidates = []
    for m in board:
        diff = abs((m["kickoff"] - target["kickoff"]).total_seconds()) / 60.0
        if diff > 150:
            continue
        hs = sim(target["home"], m["home"])
        ass = sim(target["away"], m["away"])
        q = (hs + ass) / 2.0
        # kickoff closeness only breaks otherwise-similar name matches.
        time_bonus = max(0.0, 1.0 - diff / 150.0) * 0.05
        score = q + time_bonus
        if hs >= 0.74 and ass >= 0.74:
            candidates.append((score, q, diff, m))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0]
    if best[1] < 0.82:
        return None
    if len(candidates) > 1 and best[0] - candidates[1][0] < 0.035 and best[1] < 0.94:
        return None
    return best


def text_name(v):
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        for key in ("fullName", "name", "displayName", "lastName"):
            if clean(v.get(key)):
                return clean(v.get(key))
    return ""


def extract_player(p):
    if not isinstance(p, dict):
        return None
    player = p.get("player") if isinstance(p.get("player"), dict) else p
    pid = clean(
        player.get("id") or player.get("playerId") or
        p.get("id") or p.get("playerId")
    )
    name = text_name(player.get("name")) or clean(
        player.get("displayName") or player.get("fullName") or
        p.get("name") or p.get("displayName")
    )
    if not pid and not name:
        return None

    pos = clean(
        player.get("position") or player.get("positionString") or
        player.get("positionId") or p.get("position") or p.get("positionString")
    )
    shirt = clean(
        player.get("shirtNumber") or player.get("shirt") or
        p.get("shirtNumber") or p.get("shirt")
    )
    starter_raw = p.get("starter")
    if starter_raw is None:
        starter_raw = p.get("isStarter")
    if starter_raw is None:
        starter_raw = player.get("starter")
    starter = "1" if starter_raw is True else ("0" if starter_raw is False else "")
    return {
        "player_id": pid,
        "player_name": name,
        "position": pos,
        "shirt_number": shirt,
        "starter": starter,
    }


def parse_lineups(detail):
    lineup = ((detail.get("content") or {}).get("lineup") or {})
    blocks = lineup.get("lineups") or []
    if not isinstance(blocks, list):
        blocks = []

    status = clean(
        lineup.get("lineupStatus") or lineup.get("status") or
        lineup.get("lineupsStatus")
    )
    if not status:
        status = "AVAILABLE" if blocks else "UNAVAILABLE"

    parsed = {}
    for b in blocks:
        if not isinstance(b, dict):
            continue
        tid = clean(b.get("teamId") or (b.get("team") or {}).get("id"))
        tname = clean(b.get("teamName") or (b.get("team") or {}).get("name"))
        formation = clean(b.get("formation"))
        players = []
        raw_players = b.get("players") or []
        if isinstance(raw_players, list):
            for p in raw_players:
                item = extract_player(p)
                if item:
                    players.append(item)
        parsed[tid or norm(tname)] = {
            "team_id": tid,
            "team_name": tname,
            "formation": formation,
            "players": players,
        }
    return status, parsed


def parse_sofascore_lineup(payload, target, source_match):
    status = "CONFIRMED" if payload.get("confirmed") is True else "PREDICTED"
    parsed = {}
    for side_key, source_tid, source_name in (
        ("home", source_match.get("home_id", ""), target["home"]),
        ("away", source_match.get("away_id", ""), target["away"]),
    ):
        block = payload.get(side_key) or {}
        formation = clean(block.get("formation"))
        players = []
        for raw in block.get("players") or []:
            p = raw.get("player") if isinstance(raw, dict) and isinstance(raw.get("player"), dict) else raw
            if not isinstance(p, dict):
                continue
            item = {
                "player_id": clean(p.get("id") or raw.get("playerId") if isinstance(raw, dict) else ""),
                "player_name": text_name(p.get("name")) or clean(p.get("name") or p.get("shortName")),
                "position": clean(p.get("position") or (raw.get("position") if isinstance(raw, dict) else "")),
                "shirt_number": clean(
                    (raw.get("shirtNumber") if isinstance(raw, dict) else "")
                    or p.get("shirtNumber")
                ),
                "starter": "",
            }
            if isinstance(raw, dict):
                sub = raw.get("substitute")
                if sub is not None:
                    item["starter"] = "0" if sub is True else "1"
            if item["player_id"] or item["player_name"]:
                players.append(item)
        parsed[source_tid or norm(source_name)] = {
            "team_id": source_tid,
            "team_name": source_name,
            "formation": formation,
            "players": players,
        }
    return status, parsed


def manager_from_team_payload(payload):
    def walk(node, inherited=""):
        if isinstance(node, dict):
            role = " ".join(
                clean(node.get(k)).lower()
                for k in ("position", "role", "type", "title")
                if clean(node.get(k))
            )
            context = (inherited + " " + role).strip()
            if "coach" in context or "manager" in context:
                members = node.get("members")
                if isinstance(members, list):
                    for m in members:
                        if isinstance(m, dict):
                            name = text_name(m.get("name")) or clean(m.get("displayName"))
                            if name:
                                return clean(m.get("id")), name
                name = text_name(node.get("name")) or clean(node.get("displayName"))
                if name and role:
                    return clean(node.get("id")), name
            for k, v in node.items():
                found = walk(v, context if k in ("squad", "staff", "coaches") else inherited)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item, inherited)
                if found:
                    return found
        return None
    return walk(payload) or ("", "")


def current_coach_from_payload(payload):
    history = ((payload.get("history") or {}).get("coachHistory") or []) if isinstance(payload, dict) else []
    for row in history:
        if isinstance(row, dict) and row.get("isCurrent") is True:
            return clean(row.get("id")), clean(row.get("name")), clean(row.get("startDate"))
    manager_id, manager_name = manager_from_team_payload(payload)
    return manager_id, manager_name, ""


def norm_stat_title(v):
    s = clean(v).casefold()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


STYLE_ALIASES = {
    "average_possession": ("average possession", "possession"),
    "goals_per_match": ("goals per match",),
    "expected_goals": ("expected goals", "xg"),
    "xg_conceded": ("xg conceded", "expected goals conceded"),
    "shots_on_target_per_match": ("shots on target per match", "shots on target"),
    "big_chances_created": ("big chances created",),
    "possession_won_final_3rd": ("possession won final 3rd", "possession won final third"),
    "accurate_passes_per_match": ("accurate passes per match", "accurate passes"),
    "successful_tackles_per_match": ("successful tackles per match", "successful tackles"),
    "interceptions_per_match": ("interceptions per match", "interceptions"),
}


def extract_team_style(payload, team_id, team_name, manager_id, manager_name, manager_start, fetched_at):
    stats_root = payload.get("stats") if isinstance(payload, dict) else None
    items = []

    def walk(node):
        if isinstance(node, dict):
            title = clean(node.get("title") or node.get("name") or node.get("label"))
            value = node.get("statValue")
            if value is None:
                value = node.get("value")
            if title and value is not None and not isinstance(value, (dict, list)):
                items.append((title, value))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(stats_root)
    chosen = {}
    raw = {}
    for field, aliases in STYLE_ALIASES.items():
        best = None
        for title, value in items:
            n = norm_stat_title(title)
            score = 0
            for alias in aliases:
                a = norm_stat_title(alias)
                if n == a:
                    score = max(score, 3)
                elif a in n or n in a:
                    score = max(score, 2)
            if score and (best is None or score > best[0]):
                best = (score, title, value)
        if best:
            chosen[field] = clean(best[2])
            raw[field] = {"title": best[1], "value": best[2]}

    details = payload.get("details") or {}
    return {
        "team_id": team_id,
        "team_name": team_name,
        "manager_id": manager_id,
        "manager_name": manager_name,
        "manager_start_date": manager_start,
        "season": clean(details.get("latestSeason")),
        **chosen,
        "selected_stats_json": json.dumps(raw, ensure_ascii=False, separators=(",", ":")),
        "fetched_at_hkt": fetched_at,
        "quality": "CURRENT_TEAM_STYLE_PROXY" if raw else "NO_STYLE_STATS",
        "source": "FotMob teams current-season stats",
    }


def squad_from_team_payload(payload, team_id, team_name, fetched_at):
    rows = []
    seen = set()

    def walk(node, group=""):
        if isinstance(node, dict):
            role = clean(
                node.get("position") or node.get("role") or
                node.get("title") or node.get("type")
            )
            group2 = role or group
            members = node.get("members")
            if isinstance(members, list):
                is_staff = any(x in group2.lower() for x in ("coach", "manager", "staff"))
                if not is_staff:
                    for m in members:
                        if not isinstance(m, dict):
                            continue
                        pid = clean(m.get("id") or m.get("playerId"))
                        name = text_name(m.get("name")) or clean(
                            m.get("displayName") or m.get("fullName")
                        )
                        if not pid and not name:
                            continue
                        sig = pid or norm(name)
                        if sig in seen:
                            continue
                        seen.add(sig)
                        rows.append({
                            "team_id": team_id,
                            "team_name": team_name,
                            "player_id": pid,
                            "player_name": name,
                            "position_group": clean(
                                m.get("position") or m.get("positionString") or group2
                            ),
                            "fetched_at_hkt": fetched_at,
                            "source": "FotMob teams",
                        })
            for key, value in node.items():
                if key == "members":
                    continue
                walk(value, group2 if key == "squad" else group)
        elif isinstance(node, list):
            for item in node:
                walk(item, group)

    walk(payload.get("squad") if isinstance(payload, dict) else payload)
    return rows


def manager_is_stale(row, now):
    dt = parse_dt(row.get("fetched_at_hkt"))
    return dt is None or now - dt > timedelta(days=TEAM_REFRESH_DAYS)


def main():
    now = datetime.now(HKT).replace(microsecond=0)
    fetched = now.isoformat()
    targets = current_targets(now)
    if not targets:
        write_csv(OUT, CONTEXT_COLUMNS, [])
        write_csv(PLAYERS, PLAYER_COLUMNS, [])
        print("PREMATCH_CONTEXT targets=0")
        return 0

    previous = {clean(r.get("hkjc_event_id")): r for r in read_csv(OUT)}
    previous_player_rows = read_csv(PLAYERS)
    previous_players_by_event = {}
    for r in previous_player_rows:
        eid = clean(r.get("hkjc_event_id"))
        if eid:
            previous_players_by_event.setdefault(eid, []).append(r)
    manager_rows = {
        clean(r.get("team_id")): r
        for r in read_csv(MANAGERS)
        if clean(r.get("team_id"))
    }
    squad_rows_existing = read_csv(SQUADS)
    squad_rows_by_team = {}
    for r in squad_rows_existing:
        tid = clean(r.get("team_id"))
        if tid:
            squad_rows_by_team.setdefault(tid, []).append(r)
    style_rows = {
        clean(r.get("team_id")): r
        for r in read_csv(STYLES)
        if clean(r.get("team_id"))
    }

    session = requests.Session()
    dates = {t["kickoff"].strftime("%Y%m%d") for t in targets}
    board = fotmob_match_board(session, dates)
    sofa_dates = {t["kickoff"].strftime("%Y-%m-%d") for t in targets}
    try:
        sofa_board = sofascore_board(session, sofa_dates)
    except Exception:
        sofa_board = []

    contexts = []
    matched = []
    for t in targets:
        base = {
            "fetched_at_hkt": fetched,
            "hkjc_event_id": t["hkjc_event_id"],
            "kickoff_hkt": t["kickoff_hkt"],
            "league": t["league"],
            "home": t["home"],
            "away": t["away"],
            "quality": "NO_FOTMOB_MATCH",
        }
        found = match_fixture(t, board)
        if found:
            _score, name_q, diff, m = found
            base.update({
                "fotmob_match_id": m["match_id"],
                "fotmob_league_id": m["league_id"],
                "fotmob_home_id": m["home_id"],
                "fotmob_away_id": m["away_id"],
                "match_quality": f"{name_q:.3f}",
                "quality": "MATCHED",
                "notes": f"kickoff_diff_min={diff:.0f}",
            })
            matched.append((t, base, m))
        else:
            old = previous.get(t["hkjc_event_id"])
            if old:
                for key in (
                    "fotmob_match_id", "fotmob_league_id", "fotmob_home_id",
                    "fotmob_away_id", "match_quality", "home_manager",
                    "away_manager", "home_formation", "away_formation",
                    "lineup_status", "home_lineup_count", "away_lineup_count",
                    "detail_fetched_at_hkt",
                ):
                    if clean(old.get(key)):
                        base[key] = old.get(key)
                if clean(base.get("fotmob_match_id")):
                    base["quality"] = "LAST_GOOD_MATCH"
        contexts.append(base)

    by_event = {r["hkjc_event_id"]: r for r in contexts}

    # Refresh only matches close to kickoff. Each detail response is reused for
    # formation + all lineup players; never one request per player here.
    detail_candidates = []
    for t, base, m in matched:
        mins = (t["kickoff"] - now).total_seconds() / 60.0
        if -15 <= mins <= DETAIL_WINDOW_MINUTES:
            detail_candidates.append((abs(mins), t, base, m))
    detail_candidates.sort(key=lambda x: x[0])

    player_rows = []
    fresh_player_events = set()
    detail_calls = 0
    sofa_lineup_calls = 0
    for _dist, t, base, m in detail_candidates[:MAX_DETAIL_CALLS]:
        try:
            detail = get_json(session, "/data/matchDetails", {"matchId": m["match_id"]})
            detail_calls += 1
            status, lineups = parse_lineups(detail)
            base["lineup_status"] = status
            base["detail_fetched_at_hkt"] = fetched

            # If FotMob does not publish the pre-match lineup for this match,
            # try the known Sofascore event-lineup endpoint under a separate,
            # very small request budget.
            has_players = any((v.get("players") or []) for v in lineups.values())
            lineup_source = "FotMob matchDetails"
            if not has_players and sofa_lineup_calls < MAX_SOFASCORE_LINEUP_CALLS and sofa_board:
                sofa_match = match_fixture(t, sofa_board)
                if sofa_match:
                    _sscore, _sq, _sdiff, sm = sofa_match
                    try:
                        sp = sofa_json(session, f"/event/{sm['match_id']}/lineups")
                        sofa_lineup_calls += 1
                        s_status, s_lineups = parse_sofascore_lineup(sp, t, sm)
                        if any((v.get("players") or []) for v in s_lineups.values()):
                            status, lineups = s_status, s_lineups
                            base["lineup_status"] = status
                            lineup_source = "Sofascore lineups"
                    except requests.HTTPError as exc:
                        code = getattr(exc.response, "status_code", None)
                        if code in (403, 429):
                            sofa_lineup_calls = MAX_SOFASCORE_LINEUP_CALLS
                    except Exception:
                        pass

            wrote_players = False
            for side, tid, tname in (
                ("H", m["home_id"], t["home"]),
                ("A", m["away_id"], t["away"]),
            ):
                block = lineups.get(tid)
                if block is None:
                    block = next(
                        (v for v in lineups.values() if sim(tname, v.get("team_name", "")) >= 0.90),
                        None,
                    )
                if not block:
                    continue
                formation = clean(block.get("formation"))
                if side == "H":
                    base["home_formation"] = formation
                    base["home_lineup_count"] = len(block.get("players") or [])
                else:
                    base["away_formation"] = formation
                    base["away_lineup_count"] = len(block.get("players") or [])

                for p in block.get("players") or []:
                    wrote_players = True
                    player_rows.append({
                        "fetched_at_hkt": fetched,
                        "hkjc_event_id": t["hkjc_event_id"],
                        "side": side,
                        "team_id": tid,
                        "team": tname,
                        "formation": formation,
                        "player_id": p.get("player_id", ""),
                        "player_name": p.get("player_name", ""),
                        "position": p.get("position", ""),
                        "shirt_number": p.get("shirt_number", ""),
                        "starter": p.get("starter", ""),
                        "lineup_status": status,
                        "source": lineup_source,
                    })
            if wrote_players:
                fresh_player_events.add(t["hkjc_event_id"])
        except requests.HTTPError as exc:
            code = getattr(exc.response, "status_code", None)
            base["notes"] = (clean(base.get("notes")) + f" detail_http={code}").strip()
            if code in (403, 429):
                break
        except Exception as exc:
            base["notes"] = (
                clean(base.get("notes")) + f" detail_error={type(exc).__name__}"
            ).strip()
        if REQUEST_SLEEP:
            time.sleep(REQUEST_SLEEP)

    # Manager registry: slow-changing data, refreshed very sparingly.
    teams = {}
    for _t, _base, m in matched:
        if m["home_id"]:
            teams[m["home_id"]] = m["home"]
        if m["away_id"]:
            teams[m["away_id"]] = m["away"]

    refresh_team_ids = [
        tid for tid in teams
        if tid not in manager_rows or manager_is_stale(manager_rows[tid], now)
    ][:MAX_TEAM_CALLS]

    team_calls = 0
    for tid in refresh_team_ids:
        try:
            payload = get_json(session, "/data/teams", {"id": tid, "ccode3": "HKG"})
            team_calls += 1
            manager_id, manager_name, manager_start = current_coach_from_payload(payload)
            manager_rows[tid] = {
                "team_id": tid,
                "team_name": teams[tid],
                "manager_id": manager_id,
                "manager_name": manager_name,
                "manager_start_date": manager_start,
                "fetched_at_hkt": fetched,
                "quality": "OK" if manager_name else "NO_MANAGER_FOUND",
                "source": "FotMob teams",
            }
            style_rows[tid] = extract_team_style(
                payload, tid, teams[tid], manager_id, manager_name, manager_start, fetched
            )
            fresh_squad = squad_from_team_payload(payload, tid, teams[tid], fetched)
            if fresh_squad:
                squad_rows_by_team[tid] = fresh_squad
        except requests.HTTPError as exc:
            code = getattr(exc.response, "status_code", None)
            if code in (403, 429):
                break
        except Exception:
            pass
        if REQUEST_SLEEP:
            time.sleep(REQUEST_SLEEP)

    for row in contexts:
        hid = clean(row.get("fotmob_home_id"))
        aid = clean(row.get("fotmob_away_id"))
        row["home_manager"] = clean((manager_rows.get(hid) or {}).get("manager_name"))
        row["away_manager"] = clean((manager_rows.get(aid) or {}).get("manager_name"))

        # Preserve previously collected lineup if this hourly pass did not need
        # to call matchDetails for the fixture.
        old = previous.get(row["hkjc_event_id"]) or {}
        for key in (
            "home_formation", "away_formation", "lineup_status",
            "home_lineup_count", "away_lineup_count", "detail_fetched_at_hkt",
        ):
            if not clean(row.get(key)) and clean(old.get(key)):
                row[key] = old.get(key)

    active_ids = {r["hkjc_event_id"] for r in contexts}
    for eid, rows in previous_players_by_event.items():
        if eid in active_ids and eid not in fresh_player_events:
            player_rows.extend(rows)

    player_rows.sort(
        key=lambda r: (
            clean(r.get("hkjc_event_id")),
            clean(r.get("side")),
            clean(r.get("starter")) != "1",
            clean(r.get("player_name")),
        )
    )

    all_squad_rows = []
    for tid in sorted(squad_rows_by_team):
        all_squad_rows.extend(squad_rows_by_team[tid])

    write_csv(OUT, CONTEXT_COLUMNS, contexts)
    write_csv(PLAYERS, PLAYER_COLUMNS, player_rows)
    write_csv(MANAGERS, MANAGER_COLUMNS, sorted(manager_rows.values(), key=lambda r: r["team_id"]))
    write_csv(SQUADS, SQUAD_COLUMNS, all_squad_rows)
    write_csv(STYLES, STYLE_COLUMNS, sorted(style_rows.values(), key=lambda r: r["team_id"]))

    print(
        f"PREMATCH_CONTEXT targets={len(targets)} matched={sum(bool(r.get('fotmob_match_id')) for r in contexts)} "
        f"detail_calls={detail_calls}/{MAX_DETAIL_CALLS} "
        f"sofa_lineup_calls={sofa_lineup_calls}/{MAX_SOFASCORE_LINEUP_CALLS} "
        f"lineup_players={len(player_rows)} team_calls={team_calls}/{MAX_TEAM_CALLS} "
        f"manager_registry={len(manager_rows)} squad_players={len(all_squad_rows)} "
        f"style_teams={len(style_rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
