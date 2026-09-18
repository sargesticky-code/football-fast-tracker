"""Build a recent post-match player database for Fast Tracker.

Phase 1 only. This script does not create scenario probabilities or betting
signals. HKJC finished matches are canonical. FotMob supplies post-match
lineups/player statistics when identity confidence is sufficient.

Request discipline:
- newest unprocessed HKJC results first
- only a small number of FotMob daily-board dates per run
- only a small number of matchDetails calls per run
- one matchDetails response reused for every player in that match
- 403/429 stops additional detail calls immediately
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
HKJC_HISTORY = ROOT / "data" / "hkjc_history.csv"
DB_DIR = ROOT / "data" / "player_match_db"
INDEX = DB_DIR / "match_index.csv"

HKT = ZoneInfo("Asia/Hong_Kong")
FOTMOB = os.getenv("FOTMOB_BASE_URL", "https://www.fotmob.com/api").rstrip("/")
LOOKBACK_DAYS = max(3, int(os.getenv("PLAYER_DB_LOOKBACK_DAYS", "21")))
MAX_DETAILS = max(1, int(os.getenv("PLAYER_DB_MAX_DETAILS", "4")))
MAX_BOARD_DATES = max(1, int(os.getenv("PLAYER_DB_MAX_BOARD_DATES", "4")))
SLEEP = max(0.0, float(os.getenv("PLAYER_DB_REQUEST_SLEEP", "0.45")))

INDEX_COLUMNS = [
    "captured_at_hkt", "hkjc_event_id", "kickoff_hkt", "league",
    "home", "away", "fotmob_match_id", "match_quality", "kickoff_diff_min",
    "lineup_players", "usable_player_rows", "status", "reason", "source",
]

PLAYER_COLUMNS = [
    "captured_at_hkt", "hkjc_event_id", "kickoff_hkt", "league",
    "home", "away", "fotmob_match_id", "match_quality", "side",
    "team_id", "team_name", "formation", "player_id", "player_name",
    "position", "shirt_number", "starter", "substitute",
    "minutes", "rating", "goals", "assists", "xg", "xa",
    "shots", "shots_on_target", "chances_created", "big_chances",
    "touches_box", "passes", "accurate_passes", "key_passes",
    "tackles", "interceptions", "recoveries", "duels_won",
    "aerial_duels_won", "saves", "goals_prevented",
    "yellow_cards", "red_cards", "player_stats_json", "source",
]


def clean(v):
    return "" if v is None else str(v).strip()


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


def norm(v):
    s = unicodedata.normalize("NFKD", clean(v))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).casefold()
    s = s.replace("&", " and ")
    s = re.sub(r"['’\x60]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(fc|cf|sc|afc|club|football|soccer)\b", " ", s)
    return " ".join(s.split())


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return max(0.88, min(len(a), len(b)) / max(len(a), len(b)))
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def fetch_json(session, endpoint, params):
    r = session.get(FOTMOB + endpoint, params=params, headers=headers(), timeout=12)
    r.raise_for_status()
    return r.json()


def board_for_date(session, day):
    payload = fetch_json(
        session, "/data/matches",
        {"date": day.strftime("%Y%m%d"), "timezone": "Asia/Hong_Kong", "ccode3": "HKG"},
    )
    out = []
    for lg in payload.get("leagues") or []:
        league_name = clean(lg.get("name"))
        for m in lg.get("matches") or []:
            st = m.get("status") or {}
            home = m.get("home") or {}
            away = m.get("away") or {}
            kick = parse_dt(st.get("utcTime") or m.get("utcTime"))
            if not kick:
                continue
            out.append({
                "match_id": clean(m.get("id")),
                "league": league_name,
                "kickoff": kick,
                "home": clean(home.get("name")),
                "away": clean(away.get("name")),
                "home_id": clean(home.get("id")),
                "away_id": clean(away.get("id")),
                "finished": st.get("finished") is True,
                "cancelled": st.get("cancelled") is True,
            })
    return out


def best_match(target, board):
    ranked = []
    for m in board:
        diff = abs((m["kickoff"] - target["kickoff"]).total_seconds()) / 60.0
        if diff > 150:
            continue
        hs = sim(target["home"], m["home"])
        aws = sim(target["away"], m["away"])
        time_score = max(0.0, 1.0 - diff / 150.0)

        standard = min(hs, aws) >= 0.60
        anchored_short = (
            diff <= 10
            and max(hs, aws) >= 0.85
            and min(hs, aws) >= 0.35
        )
        if not (standard or anchored_short):
            continue

        standard_score = 0.42 * hs + 0.42 * aws + 0.16 * time_score
        anchor_score = 0.55 * max(hs, aws) + 0.25 * min(hs, aws) + 0.20 * time_score
        score = max(standard_score, anchor_score if anchored_short else 0.0)
        ranked.append((score, diff, hs, aws, m))

    if not ranked:
        return None
    ranked.sort(key=lambda x: (x[0], -x[1]), reverse=True)
    best = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else 0.0
    if best[0] < 0.78:
        return None
    if best[0] < 0.92 and second and best[0] - second < 0.06:
        return None
    return {
        "quality": best[0],
        "kickoff_diff": best[1],
        "home_similarity": best[2],
        "away_similarity": best[3],
        "match": best[4],
    }


def scalar(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and math.isfinite(float(v)):
        return v
    if isinstance(v, str):
        return v.strip()
    return None


def flatten_scalars(node, prefix="", out=None):
    if out is None:
        out = {}
    if isinstance(node, dict):
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            sv = scalar(v)
            if sv is not None:
                out[key] = sv
            else:
                flatten_scalars(v, key, out)
    elif isinstance(node, list):
        # Do not explode arbitrary event arrays into thousands of columns.
        for i, v in enumerate(node[:30]):
            if isinstance(v, dict):
                flatten_scalars(v, f"{prefix}[{i}]", out)
    return out


def nk(v):
    return re.sub(r"[^a-z0-9]+", "", clean(v).casefold())


STAT_ALIASES = {
    "minutes": ("minutesplayed", "minutes", "minsplayed"),
    "rating": ("rating", "fotmobrating"),
    "goals": ("goals", "goal"),
    "assists": ("assists", "assist"),
    "xg": ("expectedgoals", "xg"),
    "xa": ("expectedassists", "xa"),
    "shots": ("totalshots", "shots"),
    "shots_on_target": ("shotsontarget",),
    "chances_created": ("chancescreated", "keypasses"),
    "big_chances": ("bigchances", "bigchancescreated"),
    "touches_box": ("touchesinoppositionbox", "touchesoppbox", "touchesinbox"),
    "passes": ("passes", "totalpasses"),
    "accurate_passes": ("accuratepasses", "successfulpasses"),
    "key_passes": ("keypasses",),
    "tackles": ("tackles", "successfultackles"),
    "interceptions": ("interceptions",),
    "recoveries": ("recoveries", "ballrecoveries"),
    "duels_won": ("duelswon",),
    "aerial_duels_won": ("aerialduelswon", "aerialswon"),
    "saves": ("saves", "keepersaves"),
    "goals_prevented": ("goalsprevented",),
    "yellow_cards": ("yellowcards",),
    "red_cards": ("redcards",),
}


def pick_stat(flat, aliases):
    # Prefer the shortest exact normalized path suffix. This avoids accidentally
    # selecting percentile/benchmark fields that merely contain the same word.
    found = []
    for path, value in flat.items():
        last = nk(path.split(".")[-1])
        full = nk(path)
        for alias in aliases:
            a = nk(alias)
            if last == a or full.endswith(a):
                found.append((0 if last == a else 1, len(path), value))
                break
    if not found:
        return ""
    found.sort(key=lambda x: (x[0], x[1]))
    return found[0][2]


def player_identity(raw):
    p = raw.get("player") if isinstance(raw, dict) and isinstance(raw.get("player"), dict) else raw
    if not isinstance(p, dict):
        return None
    pid = clean(p.get("id") or p.get("playerId") or raw.get("id") or raw.get("playerId"))
    name = clean(
        p.get("name") or p.get("fullName") or p.get("displayName")
        or raw.get("name") or raw.get("fullName")
    )
    if not pid and not name:
        return None
    pos = clean(
        p.get("position") or p.get("positionString") or p.get("positionId")
        or raw.get("position") or raw.get("positionString")
    )
    shirt = clean(p.get("shirtNumber") or raw.get("shirtNumber") or raw.get("shirt"))
    starter_raw = raw.get("starter")
    if starter_raw is None:
        starter_raw = raw.get("isStarter")
    substitute_raw = raw.get("substitute")
    if substitute_raw is None:
        substitute_raw = raw.get("isSubstitute")
    starter = "1" if starter_raw is True else ("0" if starter_raw is False else "")
    substitute = "1" if substitute_raw is True else ("0" if substitute_raw is False else "")
    if not starter and substitute:
        starter = "0" if substitute == "1" else ""
    return {
        "player_id": pid,
        "player_name": name,
        "position": pos,
        "shirt_number": shirt,
        "starter": starter,
        "substitute": substitute,
    }


def lineup_blocks(detail):
    lineup = ((detail.get("content") or {}).get("lineup") or {})
    blocks = lineup.get("lineups") or []
    return blocks if isinstance(blocks, list) else []


def player_rows_from_detail(detail, target, match_meta, captured):
    rows = []
    seen = set()
    blocks = lineup_blocks(detail)

    for block_idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        team = block.get("team") if isinstance(block.get("team"), dict) else {}
        team_id = clean(block.get("teamId") or team.get("id"))
        team_name = clean(block.get("teamName") or team.get("name"))
        formation = clean(block.get("formation"))

        if team_id and team_id == match_meta["home_id"]:
            side = "H"
            team_name = team_name or target["home"]
        elif team_id and team_id == match_meta["away_id"]:
            side = "A"
            team_name = team_name or target["away"]
        else:
            # Team ids are preferred; name comparison is a schema fallback.
            hsim = sim(team_name, target["home"])
            asim = sim(team_name, target["away"])
            side = "H" if hsim >= asim else "A"

        raw_players = []
        for key in ("players", "starters", "bench", "substitutes"):
            value = block.get(key)
            if isinstance(value, list):
                raw_players.extend(value)

        for raw in raw_players:
            if not isinstance(raw, dict):
                continue
            ident = player_identity(raw)
            if not ident:
                continue
            sig = (side, ident["player_id"] or nk(ident["player_name"]))
            if sig in seen:
                continue
            seen.add(sig)

            flat = flatten_scalars(raw)
            stats = {field: pick_stat(flat, aliases) for field, aliases in STAT_ALIASES.items()}
            rows.append({
                "captured_at_hkt": captured,
                "hkjc_event_id": target["event_id"],
                "kickoff_hkt": target["kickoff"].isoformat(timespec="minutes"),
                "league": target["league"],
                "home": target["home"],
                "away": target["away"],
                "fotmob_match_id": match_meta["match_id"],
                "match_quality": f'{target["match_quality"]:.3f}',
                "side": side,
                "team_id": team_id or (match_meta["home_id"] if side == "H" else match_meta["away_id"]),
                "team_name": team_name or (target["home"] if side == "H" else target["away"]),
                "formation": formation,
                **ident,
                **{k: clean(v) for k, v in stats.items()},
                "player_stats_json": json.dumps(flat, ensure_ascii=False, separators=(",", ":")),
                "source": "FotMob matchDetails",
            })

    return rows, len(seen)


def recent_targets(now):
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    out = []
    for r in read_csv(HKJC_HISTORY):
        if clean(r.get("payout_confirmed")).casefold() not in ("true", "1", "yes"):
            continue
        kick = parse_dt(r.get("kickoff_hkt"))
        if kick is None or kick < cutoff or kick > now - timedelta(minutes=90):
            continue
        eid = clean(r.get("hkjc_event_id"))
        if not eid:
            continue
        out.append({
            "event_id": eid,
            "kickoff": kick,
            "league": clean(r.get("tournament")),
            "home": clean(r.get("home")),
            "away": clean(r.get("away")),
        })
    out.sort(key=lambda x: x["kickoff"], reverse=True)
    return out


def month_file(kickoff):
    return DB_DIR / f'{kickoff:%Y-%m}.csv'


def merge_month(rows):
    if not rows:
        return
    by_month = {}
    for r in rows:
        dt = parse_dt(r.get("kickoff_hkt"))
        if dt:
            by_month.setdefault(month_file(dt), []).append(r)

    for path, fresh in by_month.items():
        existing = read_csv(path)
        keyed = {}
        for r in existing + fresh:
            key = (
                clean(r.get("hkjc_event_id")),
                clean(r.get("side")),
                clean(r.get("player_id")) or nk(r.get("player_name")),
            )
            keyed[key] = r
        merged = sorted(
            keyed.values(),
            key=lambda r: (
                clean(r.get("kickoff_hkt")),
                clean(r.get("hkjc_event_id")),
                clean(r.get("side")),
                clean(r.get("player_name")),
            ),
        )
        write_csv(path, PLAYER_COLUMNS, merged)


def main():
    now = datetime.now(HKT).replace(microsecond=0)
    captured = now.isoformat()
    DB_DIR.mkdir(parents=True, exist_ok=True)

    index_rows = read_csv(INDEX)
    index_by_id = {
        clean(r.get("hkjc_event_id")): r
        for r in index_rows if clean(r.get("hkjc_event_id"))
    }

    targets = [
        t for t in recent_targets(now)
        if clean((index_by_id.get(t["event_id"]) or {}).get("status")) != "OK"
    ]
    if not targets:
        write_csv(INDEX, INDEX_COLUMNS, index_rows)
        print("PLAYER_MATCH_DB due=0")
        return 0

    # Limit unique dates first; this caps the cheap daily-board requests.
    selected = []
    dates = []
    for t in targets:
        d = t["kickoff"].date()
        if d not in dates and len(dates) >= MAX_BOARD_DATES:
            continue
        if d not in dates:
            dates.append(d)
        selected.append(t)
        if len(selected) >= MAX_DETAILS * 5:
            break

    session = requests.Session()
    boards = {}
    for d in dates:
        try:
            boards[d] = board_for_date(session, d)
        except requests.HTTPError as exc:
            code = getattr(exc.response, "status_code", None)
            print(f"WARN PLAYER_DB board date={d} http={code}")
            boards[d] = []
            if code in (403, 429):
                break
        except Exception as exc:
            print(f"WARN PLAYER_DB board date={d} error={type(exc).__name__}")
            boards[d] = []
        if SLEEP:
            time.sleep(SLEEP)

    new_player_rows = []
    detail_calls = 0
    processed = 0
    blocked = False

    for t in selected:
        if detail_calls >= MAX_DETAILS or blocked:
            break

        match = best_match(t, boards.get(t["kickoff"].date(), []))
        if not match:
            index_by_id[t["event_id"]] = {
                "captured_at_hkt": captured,
                "hkjc_event_id": t["event_id"],
                "kickoff_hkt": t["kickoff"].isoformat(timespec="minutes"),
                "league": t["league"],
                "home": t["home"],
                "away": t["away"],
                "status": "NO_CONFIDENT_FOTMOB_MATCH",
                "reason": "daily-board identity confidence below threshold",
                "source": "FotMob daily board",
            }
            continue

        fm = match["match"]
        t["match_quality"] = match["quality"]
        try:
            detail = fetch_json(session, "/data/matchDetails", {"matchId": fm["match_id"]})
            detail_calls += 1
            rows, lineup_count = player_rows_from_detail(detail, t, fm, captured)
            usable = sum(1 for r in rows if clean(r.get("player_id")) and clean(r.get("player_name")))
            status = "OK" if usable >= 14 else ("PARTIAL" if usable > 0 else "NO_PLAYER_ROWS")
            reason = "" if status == "OK" else f"usable_player_rows={usable}"
            if rows:
                new_player_rows.extend(rows)
            index_by_id[t["event_id"]] = {
                "captured_at_hkt": captured,
                "hkjc_event_id": t["event_id"],
                "kickoff_hkt": t["kickoff"].isoformat(timespec="minutes"),
                "league": t["league"],
                "home": t["home"],
                "away": t["away"],
                "fotmob_match_id": fm["match_id"],
                "match_quality": f'{match["quality"]:.3f}',
                "kickoff_diff_min": f'{match["kickoff_diff"]:.1f}',
                "lineup_players": lineup_count,
                "usable_player_rows": usable,
                "status": status,
                "reason": reason,
                "source": "FotMob matchDetails",
            }
            processed += 1
        except requests.HTTPError as exc:
            code = getattr(exc.response, "status_code", None)
            index_by_id[t["event_id"]] = {
                "captured_at_hkt": captured,
                "hkjc_event_id": t["event_id"],
                "kickoff_hkt": t["kickoff"].isoformat(timespec="minutes"),
                "league": t["league"],
                "home": t["home"],
                "away": t["away"],
                "fotmob_match_id": fm["match_id"],
                "match_quality": f'{match["quality"]:.3f}',
                "kickoff_diff_min": f'{match["kickoff_diff"]:.1f}',
                "status": f"HTTP_{code}",
                "reason": "matchDetails request failed",
                "source": "FotMob matchDetails",
            }
            if code in (403, 429):
                blocked = True
        except Exception as exc:
            index_by_id[t["event_id"]] = {
                "captured_at_hkt": captured,
                "hkjc_event_id": t["event_id"],
                "kickoff_hkt": t["kickoff"].isoformat(timespec="minutes"),
                "league": t["league"],
                "home": t["home"],
                "away": t["away"],
                "fotmob_match_id": fm["match_id"],
                "match_quality": f'{match["quality"]:.3f}',
                "kickoff_diff_min": f'{match["kickoff_diff"]:.1f}',
                "status": "ERROR",
                "reason": type(exc).__name__,
                "source": "FotMob matchDetails",
            }

        if SLEEP:
            time.sleep(SLEEP)

    merge_month(new_player_rows)
    merged_index = sorted(
        index_by_id.values(),
        key=lambda r: (clean(r.get("kickoff_hkt")), clean(r.get("hkjc_event_id"))),
    )
    write_csv(INDEX, INDEX_COLUMNS, merged_index)

    status_counts = {}
    for r in merged_index:
        s = clean(r.get("status")) or "BLANK"
        status_counts[s] = status_counts.get(s, 0) + 1
    print(
        f"PLAYER_MATCH_DB lookback_days={LOOKBACK_DAYS} due={len(targets)} "
        f"dates={len(dates)}/{MAX_BOARD_DATES} detail_calls={detail_calls}/{MAX_DETAILS} "
        f"processed={processed} new_player_rows={len(new_player_rows)} "
        f"blocked={int(blocked)} statuses={status_counts}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
