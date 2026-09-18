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

HKT = ZoneInfo("Asia/Hong_Kong")
FOTMOB = os.getenv("FOTMOB_BASE_URL", "https://www.fotmob.com/api").rstrip("/")
LOOKAHEAD_HOURS = max(6, int(os.getenv("PREMATCH_LOOKAHEAD_HOURS", "36")))
DETAIL_WINDOW_MINUTES = max(30, int(os.getenv("PREMATCH_DETAIL_WINDOW_MINUTES", "180")))
MAX_DETAIL_CALLS = max(0, int(os.getenv("PREMATCH_MAX_DETAIL_CALLS", "6")))
MAX_TEAM_CALLS = max(0, int(os.getenv("PREMATCH_MAX_TEAM_CALLS", "6")))
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
    "team_id", "team_name", "manager_id", "manager_name",
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
    manager_rows = {
        clean(r.get("team_id")): r
        for r in read_csv(MANAGERS)
        if clean(r.get("team_id"))
    }

    session = requests.Session()
    dates = {t["kickoff"].strftime("%Y%m%d") for t in targets}
    board = fotmob_match_board(session, dates)

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
    detail_calls = 0
    for _dist, t, base, m in detail_candidates[:MAX_DETAIL_CALLS]:
        try:
            detail = get_json(session, "/data/matchDetails", {"matchId": m["match_id"]})
            detail_calls += 1
            status, lineups = parse_lineups(detail)
            base["lineup_status"] = status
            base["detail_fetched_at_hkt"] = fetched

            for side, tid, tname in (
                ("H", m["home_id"], t["home"]),
                ("A", m["away_id"], t["away"]),
            ):
                block = lineups.get(tid)
                if block is None:
                    # Fallback by normalized team name for schema variants.
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
                        "source": "FotMob matchDetails",
                    })
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
            manager_id, manager_name = manager_from_team_payload(payload)
            manager_rows[tid] = {
                "team_id": tid,
                "team_name": teams[tid],
                "manager_id": manager_id,
                "manager_name": manager_name,
                "fetched_at_hkt": fetched,
                "quality": "OK" if manager_name else "NO_MANAGER_FOUND",
                "source": "FotMob teams",
            }
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

    write_csv(OUT, CONTEXT_COLUMNS, contexts)
    write_csv(PLAYERS, PLAYER_COLUMNS, player_rows)
    write_csv(MANAGERS, MANAGER_COLUMNS, sorted(manager_rows.values(), key=lambda r: r["team_id"]))

    print(
        f"PREMATCH_CONTEXT targets={len(targets)} matched={sum(bool(r.get('fotmob_match_id')) for r in contexts)} "
        f"detail_calls={detail_calls}/{MAX_DETAIL_CALLS} lineup_players={len(player_rows)} "
        f"team_calls={team_calls}/{MAX_TEAM_CALLS} manager_registry={len(manager_rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
