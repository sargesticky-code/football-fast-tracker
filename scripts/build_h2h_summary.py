"""Build verified head-to-head summaries for current HKJC fixtures.

HKJC remains the canonical fixture identity. Deep H2H can be enriched from
SofaScore only after a unique, verified HKJC↔SofaScore fixture mapping.

No fuzzy name matching is allowed in this step.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "hkjc_history.csv"
CURRENT = ROOT / "data" / "hkjc_current_teams.csv"
COVERAGE = ROOT / "data" / "hkjc_history_coverage.csv"
SOFASCORE = ROOT / "data" / "sofascore_h2h_current.csv"
OUT = ROOT / "data" / "h2h_summary.csv"
HKT = ZoneInfo("Asia/Hong_Kong")
LIMIT = 5

FIELDS = [
    "fetched_at_hkt", "hkjc_event_id", "kickoff_hkt",
    "home_id", "away_id", "home", "away",
    "h2h_games", "home_wins", "draws", "away_wins",
    "home_goals", "away_goals", "avg_total_goals",
    "last5", "meetings_json", "source", "quality",
]


def read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def parse_dt(value: str):
    value = clean(value)
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HKT)
    return dt.astimezone(HKT)


def score(value):
    try:
        return int(float(clean(value)))
    except (TypeError, ValueError):
        return None


def valid_sofascore_summary(row: dict[str, str] | None) -> dict | None:
    """Return a safe SofaScore H2H override only for verified H2H rows."""
    if not row:
        return None
    if clean(row.get("mapping_status")) != "VERIFIED":
        return None
    if clean(row.get("quality")) != "H2H_OK":
        return None

    games = score(row.get("h2h_games"))
    home_wins = score(row.get("home_wins"))
    draws = score(row.get("draws"))
    away_wins = score(row.get("away_wins"))
    home_goals = score(row.get("home_goals"))
    away_goals = score(row.get("away_goals"))
    if None in (games, home_wins, draws, away_wins, home_goals, away_goals):
        return None
    if games <= 0 or home_wins + draws + away_wins != games:
        return None

    try:
        meetings = json.loads(clean(row.get("meetings_json")) or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(meetings, list) or not meetings:
        return None

    avg = clean(row.get("avg_total_goals"))
    return {
        "h2h_games": games,
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": away_wins,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "avg_total_goals": avg,
        "last5": clean(row.get("last5")),
        "meetings_json": json.dumps(meetings[:LIMIT], ensure_ascii=False, separators=(",", ":")),
        "source": "SOFASCORE verified direct H2H",
        "quality": "H2H_OK",
    }


def write(rows: list[dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})
    tmp.replace(OUT)


def main() -> int:
    current = read(CURRENT)
    history = read(HISTORY)
    coverage_rows = read(COVERAGE)
    sofa_rows = read(SOFASCORE)
    sofa_by_event = {
        clean(r.get("hkjc_event_id")): r
        for r in sofa_rows
        if clean(r.get("hkjc_event_id"))
    }
    coverage = {
        clean(r.get("team_id")): clean(r.get("status"))
        for r in coverage_rows
        if clean(r.get("team_id"))
    }

    fetched_at = datetime.now(HKT).replace(microsecond=0).isoformat()
    output: list[dict] = []
    sofa_used = 0

    for fixture in current:
        event_id = clean(fixture.get("hkjc_event_id"))
        home_id = clean(fixture.get("home_id"))
        away_id = clean(fixture.get("away_id"))
        kickoff = parse_dt(fixture.get("kickoff_hkt", ""))
        if not event_id or not home_id or not away_id or not kickoff:
            continue

        meetings = []
        for past in history:
            ph = clean(past.get("home_id"))
            pa = clean(past.get("away_id"))
            if {ph, pa} != {home_id, away_id}:
                continue
            when = parse_dt(past.get("kickoff_hkt", ""))
            if not when or when >= kickoff:
                continue
            hg = score(past.get("home_goals"))
            ag = score(past.get("away_goals"))
            if hg is None or ag is None:
                continue

            same_orientation = ph == home_id and pa == away_id
            current_home_goals = hg if same_orientation else ag
            current_away_goals = ag if same_orientation else hg
            result = (
                "H" if current_home_goals > current_away_goals
                else "A" if current_home_goals < current_away_goals
                else "D"
            )
            meetings.append({
                "_when": when,
                "kickoff_hkt": when.isoformat(),
                "tournament": clean(past.get("tournament")),
                "home": clean(past.get("home")),
                "away": clean(past.get("away")),
                "home_goals": hg,
                "away_goals": ag,
                "current_home_goals": current_home_goals,
                "current_away_goals": current_away_goals,
                "result": result,
                "hkjc_event_id": clean(past.get("hkjc_event_id")),
                "match_id": clean(past.get("match_id")),
            })

        meetings.sort(key=lambda x: x["_when"], reverse=True)
        recent = meetings[:LIMIT]
        for x in recent:
            x.pop("_when", None)

        n = len(recent)
        home_wins = sum(x["result"] == "H" for x in recent)
        draws = sum(x["result"] == "D" for x in recent)
        away_wins = sum(x["result"] == "A" for x in recent)
        home_goals = sum(x["current_home_goals"] for x in recent)
        away_goals = sum(x["current_away_goals"] for x in recent)
        both_bootstrapped = (
            coverage.get(home_id) == "BOOTSTRAPPED"
            and coverage.get(away_id) == "BOOTSTRAPPED"
        )

        if n:
            quality = "H2H_OK"
        elif both_bootstrapped:
            quality = "NO_PREVIOUS_H2H_IN_AVAILABLE_HISTORY"
        else:
            quality = "HISTORY_PARTIAL"

        summary = {
            "h2h_games": n,
            "home_wins": home_wins,
            "draws": draws,
            "away_wins": away_wins,
            "home_goals": home_goals,
            "away_goals": away_goals,
            "avg_total_goals": f"{((home_goals + away_goals) / n):.2f}" if n else "",
            "last5": "".join(x["result"] for x in recent),
            "meetings_json": json.dumps(recent, ensure_ascii=False, separators=(",", ":")),
            "source": "HKJC accumulated matchResult history",
            "quality": quality,
        }

        sofa = valid_sofascore_summary(sofa_by_event.get(event_id))
        if sofa is not None:
            summary = sofa
            sofa_used += 1

        output.append({
            "fetched_at_hkt": fetched_at,
            "hkjc_event_id": event_id,
            "kickoff_hkt": kickoff.isoformat(),
            "home_id": home_id,
            "away_id": away_id,
            "home": clean(fixture.get("home")),
            "away": clean(fixture.get("away")),
            **summary,
        })

    output.sort(key=lambda r: (r["kickoff_hkt"], r["hkjc_event_id"]))
    write(output)
    counts = {}
    for r in output:
        counts[r["quality"]] = counts.get(r["quality"], 0) + 1
    print(
        "H2H_SUMMARY "
        f"fixtures={len(output)} history_rows={len(history)} sofascore_rows={len(sofa_rows)} "
        f"sofascore_used={sofa_used} "
        + " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
