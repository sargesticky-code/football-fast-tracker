"""Bounded current-player profile enrichment for Fast Tracker.

Uses FotMob playerData only for players belonging to HKJC-targeted teams.
Priority is confirmed/probable lineup players, then active squad players for the
soonest fixtures. Profiles are cached for seven days and only a small number of
players are refreshed per run.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
CONTEXT = ROOT / "data" / "prematch_context_current.csv"
LINEUPS = ROOT / "data" / "prematch_players_current.csv"
SQUADS = ROOT / "data" / "team_squad_registry.csv"
OUT = ROOT / "data" / "player_profile_registry.csv"

HKT = ZoneInfo("Asia/Hong_Kong")
FOTMOB = os.getenv("FOTMOB_BASE_URL", "https://www.fotmob.com/api").rstrip("/")
MAX_CALLS = max(0, int(os.getenv("PLAYER_PROFILE_MAX_CALLS", "6")))
REFRESH_DAYS = max(1, int(os.getenv("PLAYER_PROFILE_REFRESH_DAYS", "7")))
TARGET_HOURS = max(3, int(os.getenv("PLAYER_PROFILE_TARGET_HOURS", "12")))
REQUEST_SLEEP = max(0.0, float(os.getenv("PLAYER_PROFILE_REQUEST_SLEEP", "0.45")))

COLUMNS = [
    "fetched_at_hkt", "player_id", "player_name", "team_id", "team_name",
    "position", "is_captain", "injury_status", "injury_description",
    "injury_return_date", "main_league_id", "main_league", "season",
    "tournament", "appearances", "starts", "minutes", "goals", "assists",
    "xg", "xa", "rating", "shots", "shots_on_target", "chances_created",
    "touches_box", "passes", "key_passes", "tackles", "interceptions",
    "recoveries", "duels_won", "aerial_duels_won", "saves",
    "goals_prevented", "clean_sheets", "selected_stats_json",
    "quality", "source",
]


def clean(v):
    return "" if v is None else str(v).strip()


def read_csv(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in COLUMNS})
    tmp.replace(path)


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


def fetch_player(session, player_id):
    r = session.get(
        FOTMOB + "/data/playerData",
        params={"id": player_id, "includeMarketValues": "false"},
        headers=headers(),
        timeout=12,
    )
    r.raise_for_status()
    return r.json()


def norm_title(v):
    s = clean(v).casefold()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


ALIASES = {
    "appearances": ("appearances", "matches played", "games played"),
    "starts": ("starts", "started"),
    "minutes": ("minutes played", "minutes"),
    "goals": ("goals",),
    "assists": ("assists",),
    "xg": ("expected goals", "xg"),
    "xa": ("expected assists", "xa"),
    "rating": ("fotmob rating", "rating"),
    "shots": ("shots", "total shots"),
    "shots_on_target": ("shots on target",),
    "chances_created": ("chances created", "big chances created"),
    "touches_box": ("touches in opposition box", "touches in box"),
    "passes": ("accurate passes", "passes"),
    "key_passes": ("key passes",),
    "tackles": ("successful tackles", "tackles won", "tackles"),
    "interceptions": ("interceptions",),
    "recoveries": ("recoveries", "ball recoveries"),
    "duels_won": ("duels won",),
    "aerial_duels_won": ("aerial duels won",),
    "saves": ("saves", "saves per match"),
    "goals_prevented": ("goals prevented",),
    "clean_sheets": ("clean sheets",),
}


def recent_tournament(payload):
    seasons = payload.get("statSeasons") or []
    if not seasons:
        return "", "", []

    # API order is normally newest first; prefer the first season that contains
    # tournaments and, when possible, the player's main league.
    main_id = clean((payload.get("mainLeague") or {}).get("leagueId"))
    for season in seasons:
        tournaments = season.get("tournaments") or []
        if not tournaments:
            continue
        picked = None
        if main_id:
            picked = next(
                (t for t in tournaments if clean(t.get("tournamentId")) == main_id),
                None,
            )
        picked = picked or tournaments[0]
        return clean(season.get("seasonName")), clean(picked.get("name")), picked.get("categories") or []
    return "", "", []


def extract_stats(categories):
    all_items = []

    def walk(node):
        if isinstance(node, dict):
            title = clean(node.get("title") or node.get("name") or node.get("label"))
            value = node.get("statValue")
            if value is None and not isinstance(node.get("value"), (dict, list)):
                value = node.get("value")
            if title and value is not None and not isinstance(value, (dict, list)):
                all_items.append({
                    "title": title,
                    "norm": norm_title(title),
                    "value": value,
                    "per90": node.get("per90"),
                    "percentile": node.get("percentileRankPer90")
                        if node.get("percentileRankPer90") is not None
                        else node.get("percentileRank"),
                })
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(categories)

    picked = {}
    used = {}
    for field, aliases in ALIASES.items():
        best = None
        for item in all_items:
            n = item["norm"]
            score = 0
            for alias in aliases:
                a = norm_title(alias)
                if n == a:
                    score = max(score, 3)
                elif a in n or n in a:
                    score = max(score, 2)
            if score and (best is None or score > best[0]):
                best = (score, item)
        if best:
            item = best[1]
            picked[field] = item["value"]
            used[field] = {
                "title": item["title"],
                "value": item["value"],
                "per90": item["per90"],
                "percentile": item["percentile"],
            }
    return picked, used


def player_row(payload, fallback, now):
    primary = payload.get("primaryTeam") or {}
    position = ((payload.get("positionDescription") or {}).get("primaryPosition") or {})
    injury = payload.get("injuryInformation") or {}
    main = payload.get("mainLeague") or {}
    season, tournament, categories = recent_tournament(payload)
    stats, selected = extract_stats(categories)

    return {
        "fetched_at_hkt": now.isoformat(),
        "player_id": clean(payload.get("id") or fallback.get("player_id")),
        "player_name": clean(payload.get("name") or fallback.get("player_name")),
        "team_id": clean(primary.get("teamId") or fallback.get("team_id")),
        "team_name": clean(primary.get("teamName") or fallback.get("team_name")),
        "position": clean(position.get("label") or position.get("key") or fallback.get("position")),
        "is_captain": "1" if payload.get("isCaptain") is True else "0",
        "injury_status": clean(injury.get("status")),
        "injury_description": clean(injury.get("description")),
        "injury_return_date": clean(injury.get("returnDate")),
        "main_league_id": clean(main.get("leagueId")),
        "main_league": clean(main.get("leagueName")),
        "season": season,
        "tournament": tournament,
        **{k: clean(v) for k, v in stats.items()},
        "selected_stats_json": json.dumps(selected, ensure_ascii=False, separators=(",", ":")),
        "quality": "OK",
        "source": "FotMob playerData",
    }


def profile_stale(row, now):
    dt = parse_dt(row.get("fetched_at_hkt"))
    return dt is None or now - dt > timedelta(days=REFRESH_DAYS)


def position_priority(v):
    n = norm_title(v)
    if any(x in n for x in ("forward", "attacker", "striker", "attack")):
        return 0
    if any(x in n for x in ("midfield", "wing")):
        return 1
    if any(x in n for x in ("keeper", "goalkeeper")):
        return 2
    if any(x in n for x in ("defender", "back")):
        return 3
    return 4


def main():
    now = datetime.now(HKT).replace(microsecond=0)
    context = read_csv(CONTEXT)
    lineups = read_csv(LINEUPS)
    squads = read_csv(SQUADS)
    existing_rows = read_csv(OUT)
    registry = {
        clean(r.get("player_id")): r
        for r in existing_rows if clean(r.get("player_id"))
    }

    cutoff = now + timedelta(hours=TARGET_HOURS)
    active_team_rank = {}
    for r in context:
        kick = parse_dt(r.get("kickoff_hkt"))
        if kick is None or not (now - timedelta(minutes=20) <= kick <= cutoff):
            continue
        rank = kick.timestamp()
        for key in ("fotmob_home_id", "fotmob_away_id"):
            tid = clean(r.get(key))
            if tid:
                active_team_rank[tid] = min(rank, active_team_rank.get(tid, rank))

    candidates = {}
    # Confirmed/probable lineups always take priority.
    for r in lineups:
        pid = clean(r.get("player_id"))
        tid = clean(r.get("team_id"))
        if not pid or tid not in active_team_rank:
            continue
        candidates[pid] = {
            "player_id": pid,
            "player_name": clean(r.get("player_name")),
            "team_id": tid,
            "team_name": clean(r.get("team")),
            "position": clean(r.get("position")),
            "priority": -1,
            "kick_rank": active_team_rank[tid],
        }

    # Fill gaps from active squad registries. Never-fetched/stale players only.
    for r in squads:
        pid = clean(r.get("player_id"))
        tid = clean(r.get("team_id"))
        if not pid or tid not in active_team_rank or pid in candidates:
            continue
        candidates[pid] = {
            "player_id": pid,
            "player_name": clean(r.get("player_name")),
            "team_id": tid,
            "team_name": clean(r.get("team_name")),
            "position": clean(r.get("position_group")),
            "priority": position_priority(r.get("position_group")),
            "kick_rank": active_team_rank[tid],
        }

    due = []
    for pid, item in candidates.items():
        old = registry.get(pid)
        if old is None or profile_stale(old, now):
            never = 0 if old is None else 1
            due.append((item["priority"], item["kick_rank"], never, pid, item))
    due.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

    session = requests.Session()
    refreshed = 0
    stopped = False
    for _priority, _kick, _never, pid, item in due[:MAX_CALLS]:
        try:
            payload = fetch_player(session, pid)
            row = player_row(payload, item, now)
            if row["player_id"]:
                registry[row["player_id"]] = row
                refreshed += 1
        except requests.HTTPError as exc:
            code = getattr(exc.response, "status_code", None)
            if code in (403, 429):
                stopped = True
                break
        except Exception:
            # Keep the prior profile; fail closed instead of writing guessed stats.
            pass
        if REQUEST_SLEEP:
            time.sleep(REQUEST_SLEEP)

    rows = sorted(
        registry.values(),
        key=lambda r: (clean(r.get("team_name")), clean(r.get("position")), clean(r.get("player_name"))),
    )
    write_csv(OUT, rows)
    print(
        f"PLAYER_PROFILE active_teams={len(active_team_rank)} candidates={len(candidates)} "
        f"due={len(due)} refreshed={refreshed}/{MAX_CALLS} registry={len(rows)} "
        f"stopped_on_block={int(stopped)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
