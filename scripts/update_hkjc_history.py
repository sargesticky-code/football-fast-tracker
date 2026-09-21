"""Incrementally maintain compact HKJC results history for current Fast Tracker teams.

This script uses HKJC's matchResult GraphQL history, keyed by stable HKJC team
ids. A separate coverage registry records which team ids were explicitly
bootstrapped; merely appearing as an opponent in somebody else's history never
counts as complete coverage.

First explicit sight of a team: bootstrap the most recent 12 calendar months.
Explicitly bootstrapped team: refresh the current and previous calendar month.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import json
import os
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from hkjc.scraper import HKJCFootball

HKT = ZoneInfo("Asia/Hong_Kong")
ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "hkjc_current.csv"
HISTORY = ROOT / "data" / "hkjc_history.csv"
TEAM_MAP = ROOT / "data" / "hkjc_current_teams.csv"
COVERAGE = ROOT / "data" / "hkjc_history_coverage.csv"

BOOTSTRAP_MONTHS = max(2, int(os.getenv("HKJC_HISTORY_BOOTSTRAP_MONTHS", "2")))
REFRESH_MONTHS = max(1, int(os.getenv("HKJC_HISTORY_REFRESH_MONTHS", "2")))
REQUEST_SLEEP = max(0.0, float(os.getenv("HKJC_HISTORY_REQUEST_SLEEP", "0.05")))
MAX_BOOTSTRAP_TEAMS = max(0, int(os.getenv("HKJC_HISTORY_MAX_BOOTSTRAP_TEAMS", "12")))
MAX_REFRESH_TEAMS = max(0, int(os.getenv("HKJC_HISTORY_MAX_REFRESH_TEAMS", "24")))

HISTORY_COLUMNS = [
    "match_id", "hkjc_event_id", "kickoff_hkt", "tournament",
    "home_id", "away_id", "home", "away", "home_goals", "away_goals",
    "payout_confirmed", "fetched_at_hkt",
]
TEAM_COLUMNS = [
    "fetched_at_hkt", "hkjc_event_id", "match_id", "kickoff_hkt",
    "tournament", "home_id", "away_id", "home", "away",
]
COVERAGE_COLUMNS = [
    "team_id", "status", "bootstrap_months", "first_bootstrap_hkt",
    "last_refresh_hkt", "last_mode", "successful_months", "history_games",
]


def month_windows(months: int) -> list[tuple[int, int]]:
    y, m = date.today().year, date.today().month
    out: list[tuple[int, int]] = []
    for _ in range(months):
        out.append((y, m))
        if m == 1:
            y, m = y - 1, 12
        else:
            m -= 1
    return out


def stage(results, rtype: int, sid: int):
    return next(
        (r for r in (results or []) if r.get("resultType") == rtype and r.get("stageId") == sid),
        None,
    )


def valid_pair(entry) -> bool:
    return bool(
        entry
        and isinstance(entry.get("homeResult"), int)
        and entry.get("homeResult") >= 0
        and isinstance(entry.get("awayResult"), int)
        and entry.get("awayResult") >= 0
    )


def normalize_result(m: dict, fetched_at: str) -> dict | None:
    ft = stage(m.get("results"), 1, 5)
    if not valid_pair(ft):
        return None
    home = m.get("homeTeam") or {}
    away = m.get("awayTeam") or {}
    tourn = m.get("tournament") or {}
    match_id = str(m.get("id") or "").strip()
    if not match_id:
        return None
    return {
        "match_id": match_id,
        "hkjc_event_id": str(m.get("frontEndId") or "").strip(),
        "kickoff_hkt": str(m.get("kickOffTime") or m.get("matchDate") or "").strip(),
        "tournament": str(tourn.get("code") or "").strip(),
        "home_id": str(home.get("id") or "").strip(),
        "away_id": str(away.get("id") or "").strip(),
        "home": str(home.get("name_en") or home.get("name_ch") or "").strip(),
        "away": str(away.get("name_en") or away.get("name_ch") or "").strip(),
        "home_goals": ft.get("homeResult"),
        "away_goals": ft.get("awayResult"),
        "payout_confirmed": ft.get("payoutConfirmed", ""),
        "fetched_at_hkt": fetched_at,
    }


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
    tmp.replace(path)


def current_fixture_map(raw_listing: list[dict], wanted_ids: set[str], fetched_at: str) -> list[dict]:
    out: list[dict] = []
    for m in raw_listing:
        event_id = str(m.get("frontEndId") or "").strip()
        if not event_id or event_id not in wanted_ids:
            continue
        home = m.get("homeTeam") or {}
        away = m.get("awayTeam") or {}
        tourn = m.get("tournament") or {}
        row = {
            "fetched_at_hkt": fetched_at,
            "hkjc_event_id": event_id,
            "match_id": str(m.get("id") or "").strip(),
            "kickoff_hkt": str(m.get("kickOffTime") or "").strip(),
            "tournament": str(tourn.get("code") or "").strip(),
            "home_id": str(home.get("id") or "").strip(),
            "away_id": str(away.get("id") or "").strip(),
            "home": str(home.get("name_en") or home.get("name_ch") or "").strip(),
            "away": str(away.get("name_en") or away.get("name_ch") or "").strip(),
        }
        if row["home_id"] and row["away_id"]:
            out.append(row)
    out.sort(key=lambda r: (r.get("kickoff_hkt", ""), r.get("hkjc_event_id", "")))
    return out


def map_team_ids(rows: list[dict[str, str]]) -> set[str]:
    return set(ordered_team_ids(rows))


def ordered_team_ids(rows: list[dict[str, str]]) -> list[str]:
    """Return unique team ids in fixture order (kickoff, then event id)."""
    out: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for key in ("home_id", "away_id"):
            value = str(r.get(key) or "").strip()
            if value and value not in seen:
                seen.add(value)
                out.append(value)
    return out


def count_team_games(by_match: dict[str, dict], team_id: str) -> int:
    return sum(
        1 for r in by_match.values()
        if str(r.get("home_id") or "") == team_id or str(r.get("away_id") or "") == team_id
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-list", required=True, help="Raw HKJC list_matches() JSON")
    args = ap.parse_args()

    if not FEED.exists():
        raise SystemExit("missing data/hkjc_current.csv")
    with FEED.open(encoding="utf-8-sig", newline="") as fh:
        feed_rows = list(csv.DictReader(fh))
    model_targets = [
        r for r in feed_rows
        if str(r.get("hkjc_event_id") or "").strip()
        and str(r.get("selling") or "").strip() in ("1", "true", "TRUE")
        and all(str(r.get(k) or "").strip() for k in ("had_home", "had_draw", "had_away"))
    ]
    wanted_ids = {str(r.get("hkjc_event_id") or "").strip() for r in model_targets}
    if not wanted_ids:
        write_csv(TEAM_MAP, TEAM_COLUMNS, [])
        print("HKJC_HISTORY current_hkjc_had_events=0")
        return 0

    raw_listing = json.loads(Path(args.raw_list).read_text(encoding="utf-8-sig"))
    if not isinstance(raw_listing, list):
        raise SystemExit("raw HKJC match listing is not a list")

    # Preserve the previous explicit target map for one-time migration when the
    # coverage registry is first introduced.
    prior_team_map = load_csv(TEAM_MAP)
    coverage_rows = load_csv(COVERAGE)
    coverage: dict[str, dict[str, str]] = {
        str(r.get("team_id") or "").strip(): r
        for r in coverage_rows if str(r.get("team_id") or "").strip()
    }
    if not coverage and prior_team_map:
        migration_time = datetime.now(HKT).replace(microsecond=0).isoformat()
        for team_id in sorted(map_team_ids(prior_team_map)):
            coverage[team_id] = {
                "team_id": team_id,
                "status": "BOOTSTRAPPED",
                "bootstrap_months": str(BOOTSTRAP_MONTHS),
                "first_bootstrap_hkt": migration_time,
                "last_refresh_hkt": migration_time,
                "last_mode": "MIGRATED_PRIOR_TARGET",
                "successful_months": str(BOOTSTRAP_MONTHS),
                "history_games": "",
            }
        print(f"HKJC_HISTORY_COVERAGE migrated_prior_targets={len(coverage)}")

    fetched_at = datetime.now(HKT).replace(microsecond=0).isoformat()
    teams = current_fixture_map(raw_listing, wanted_ids, fetched_at)
    write_csv(TEAM_MAP, TEAM_COLUMNS, teams)
    missing_events = wanted_ids - {r["hkjc_event_id"] for r in teams}
    if missing_events:
        print("WARN HKJC_HISTORY missing_current_ids=" + ",".join(sorted(missing_events)))

    existing = load_csv(HISTORY)
    by_match: dict[str, dict] = {
        str(r.get("match_id") or "").strip(): r
        for r in existing
        if str(r.get("match_id") or "").strip()
    }

    all_current_team_ids = ordered_team_ids(teams)

    # Hard request budget. HKJC's results endpoint retains roughly the last
    # 30 days, so a two-calendar-month window is sufficient to straddle the
    # month boundary. Bootstrapping more teams with two calls each is both
    # cheaper and faster than querying twelve mostly-empty historical months.
    bootstrapped = [
        tid for tid in all_current_team_ids
        if coverage.get(tid, {}).get("status") == "BOOTSTRAPPED"
    ]
    bootstrapped.sort(key=lambda tid: coverage.get(tid, {}).get("last_refresh_hkt") or "")
    refresh_ids = bootstrapped[:MAX_REFRESH_TEAMS] if MAX_REFRESH_TEAMS else []

    bootstrap_candidates = [
        tid for tid in all_current_team_ids
        if coverage.get(tid, {}).get("status") != "BOOTSTRAPPED"
    ]
    bootstrap_ids = bootstrap_candidates[:MAX_BOOTSTRAP_TEAMS] if MAX_BOOTSTRAP_TEAMS else []
    deferred_ids = set(all_current_team_ids) - set(refresh_ids) - set(bootstrap_ids)

    for team_id in sorted(deferred_ids):
        if coverage.get(team_id, {}).get("status") == "BOOTSTRAPPED":
            continue
        row = dict(coverage.get(team_id, {})) if coverage.get(team_id) else {"team_id": team_id}
        row["status"] = row.get("status") or "PENDING"
        row["bootstrap_months"] = row.get("bootstrap_months") or str(BOOTSTRAP_MONTHS)
        row["last_mode"] = "DEFERRED_BUDGET"
        row["history_games"] = str(count_team_games(by_match, team_id))
        coverage[team_id] = row

    current_team_ids = sorted(set(refresh_ids) | set(bootstrap_ids))
    print(
        f"HKJC_HISTORY_BUDGET active_teams={len(all_current_team_ids)} "
        f"refresh_selected={len(refresh_ids)}/{MAX_REFRESH_TEAMS} "
        f"bootstrap_selected={len(bootstrap_ids)}/{MAX_BOOTSTRAP_TEAMS} "
        f"deferred={len(deferred_ids)}"
    )

    fb = HKJCFootball()
    calls = 0
    inserted = 0
    refreshed = 0

    bootstrap_windows = month_windows(BOOTSTRAP_MONTHS)
    refresh_windows = month_windows(REFRESH_MONTHS)

    for team_id in current_team_ids:
        cov = coverage.get(team_id, {})
        is_bootstrapped = cov.get("status") == "BOOTSTRAPPED"
        windows = refresh_windows if is_bootstrapped else bootstrap_windows
        mode = "refresh" if is_bootstrapped else "bootstrap"
        team_new = 0
        successful_months = 0
        for y, m in reversed(windows):
            sd = f"{y:04d}-{m:02d}-01"
            ed = f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
            try:
                result = fb.fetch_results(start_date=sd, end_date=ed, team_id=team_id)
            except Exception as exc:
                print(f"WARN HKJC_HISTORY team={team_id} month={y:04d}{m:02d} error={type(exc).__name__}:{exc}")
                continue
            calls += 1
            successful_months += 1
            for raw in result.get("matches") or []:
                row = normalize_result(raw, fetched_at)
                if not row:
                    continue
                old = by_match.get(row["match_id"])
                if old is None:
                    inserted += 1
                    team_new += 1
                else:
                    refreshed += 1
                by_match[row["match_id"]] = row
            if REQUEST_SLEEP:
                time.sleep(REQUEST_SLEEP)

        row = dict(cov) if cov else {"team_id": team_id}
        if mode == "bootstrap":
            min_success = max(1, (BOOTSTRAP_MONTHS * 3 + 3) // 4)
            if successful_months >= min_success:
                row["status"] = "BOOTSTRAPPED"
                row["bootstrap_months"] = str(BOOTSTRAP_MONTHS)
                row["first_bootstrap_hkt"] = row.get("first_bootstrap_hkt") or fetched_at
            else:
                row["status"] = "PARTIAL"
        row["last_refresh_hkt"] = fetched_at
        row["last_mode"] = mode.upper()
        row["successful_months"] = str(successful_months)
        row["history_games"] = str(count_team_games(by_match, team_id))
        coverage[team_id] = row
        print(
            f"HKJC_HISTORY_TEAM id={team_id} mode={mode} months={len(windows)} "
            f"success={successful_months} new={team_new} games={row['history_games']} status={row.get('status','')}"
        )

    history_rows = sorted(
        by_match.values(),
        key=lambda r: (str(r.get("kickoff_hkt") or ""), str(r.get("match_id") or "")),
    )
    coverage_out = sorted(coverage.values(), key=lambda r: r.get("team_id", ""))
    write_csv(HISTORY, HISTORY_COLUMNS, history_rows)
    write_csv(COVERAGE, COVERAGE_COLUMNS, coverage_out)
    print(
        f"HKJC_HISTORY events={len(wanted_ids)} current_teams={len(all_current_team_ids)} processed_teams={len(current_team_ids)} "
        f"rows={len(history_rows)} inserted={inserted} refreshed={refreshed} calls={calls} "
        f"coverage={len(coverage_out)} bootstrap_months={BOOTSTRAP_MONTHS} refresh_months={REFRESH_MONTHS}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
