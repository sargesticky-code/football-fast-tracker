"""Slow Phase-1 SofaScore H2H worker.

Reads current HKJC fixtures, resolves only identity-safe exact SofaScore events,
then fetches direct H2H for a bounded number of verified events.

This worker is intentionally prematch/slow-plane only. It must never be used as
the 5-second live-score loop.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.sofascore_h2h import (
    FixtureIdentity,
    SofascoreClient,
    match_scheduled_event,
    normalize_h2h_events,
    parse_timestamp,
    summarize_h2h,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "hkjc_current_teams.csv"
DEFAULT_OUTPUT = ROOT / "data" / "sofascore_h2h_current.csv"
HKT = ZoneInfo("Asia/Hong_Kong")
MAX_H2H_EVENTS = max(0, int(os.getenv("SOFASCORE_H2H_MAX_EVENTS", "30")))

FIELDS = [
    "fetched_at_utc",
    "hkjc_event_id",
    "kickoff_hkt",
    "home_id",
    "away_id",
    "home",
    "away",
    "sofascore_event_id",
    "sofascore_home_id",
    "sofascore_away_id",
    "sofascore_home",
    "sofascore_away",
    "sofascore_tournament",
    "kickoff_delta_seconds",
    "mapping_status",
    "mapping_reason",
    "h2h_games",
    "home_wins",
    "draws",
    "away_wins",
    "home_goals",
    "away_goals",
    "avg_total_goals",
    "last5",
    "meetings_json",
    "source",
    "quality",
]


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in FIELDS})
    tmp.replace(path)


def fixture_from_row(row: dict[str, str]) -> FixtureIdentity | None:
    event_id = _clean(row.get("hkjc_event_id"))
    kickoff = parse_timestamp(row.get("kickoff_hkt"))
    home = _clean(row.get("home"))
    away = _clean(row.get("away"))
    if not event_id or kickoff is None or not home or not away:
        return None
    return FixtureIdentity(
        hkjc_event_id=event_id,
        kickoff=kickoff,
        home=home,
        away=away,
        tournament=_clean(row.get("tournament")),
    )


def schedule_dates(fixtures: list[FixtureIdentity]) -> list[str]:
    """Dates worth requesting from SofaScore.

    Query both UTC and Hong Kong calendar dates because public daily feeds can
    straddle midnight differently. Exact kickoff matching remains the safety
    gate after the schedules are combined.
    """
    dates: set[str] = set()
    for fixture in fixtures:
        dates.add(fixture.kickoff.astimezone(timezone.utc).date().isoformat())
        dates.add(fixture.kickoff.astimezone(HKT).date().isoformat())
    return sorted(dates)


def combine_schedules(payloads: list[dict]) -> dict:
    events: dict[int, dict] = {}
    for payload in payloads:
        rows = payload.get("events")
        if not isinstance(rows, list):
            continue
        for event in rows:
            if not isinstance(event, dict) or not isinstance(event.get("id"), int):
                continue
            events[event["id"]] = event
    return {"events": list(events.values())}


def build_sofascore_h2h(
    current_rows: list[dict[str, str]],
    *,
    client: SofascoreClient,
    max_h2h_events: int = MAX_H2H_EVENTS,
) -> list[dict]:
    fixtures_by_id: dict[str, FixtureIdentity] = {}
    source_row_by_id: dict[str, dict[str, str]] = {}
    for row in current_rows:
        fixture = fixture_from_row(row)
        if fixture is None:
            continue
        fixtures_by_id[fixture.hkjc_event_id] = fixture
        source_row_by_id[fixture.hkjc_event_id] = row

    fixtures = sorted(fixtures_by_id.values(), key=lambda f: (f.kickoff, f.hkjc_event_id))
    payloads = [client.scheduled_events(day) for day in schedule_dates(fixtures)]
    combined = combine_schedules(payloads)
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    output: list[dict] = []
    h2h_calls = 0
    for fixture in fixtures:
        raw = source_row_by_id[fixture.hkjc_event_id]
        mapping = match_scheduled_event(fixture, combined)
        base = {
            "fetched_at_utc": fetched_at,
            "hkjc_event_id": fixture.hkjc_event_id,
            "kickoff_hkt": fixture.kickoff.astimezone(HKT).isoformat(),
            "home_id": _clean(raw.get("home_id")),
            "away_id": _clean(raw.get("away_id")),
            "home": fixture.home,
            "away": fixture.away,
            "sofascore_event_id": mapping.event_id or "",
            "sofascore_home_id": mapping.home_team_id or "",
            "sofascore_away_id": mapping.away_team_id or "",
            "sofascore_home": mapping.home_name,
            "sofascore_away": mapping.away_name,
            "sofascore_tournament": mapping.tournament,
            "kickoff_delta_seconds": (
                "" if mapping.kickoff_delta_seconds is None else f"{mapping.kickoff_delta_seconds:.0f}"
            ),
            "mapping_status": mapping.status,
            "mapping_reason": mapping.reason,
            "source": "SOFASCORE",
        }

        if mapping.status != "VERIFIED":
            output.append(
                {
                    **base,
                    "h2h_games": 0,
                    "home_wins": 0,
                    "draws": 0,
                    "away_wins": 0,
                    "home_goals": 0,
                    "away_goals": 0,
                    "avg_total_goals": "",
                    "last5": "",
                    "meetings_json": "[]",
                    "quality": "UNMAPPED" if mapping.status == "UNMAPPED" else mapping.status,
                }
            )
            continue

        if h2h_calls >= max_h2h_events:
            output.append(
                {
                    **base,
                    "h2h_games": 0,
                    "home_wins": 0,
                    "draws": 0,
                    "away_wins": 0,
                    "home_goals": 0,
                    "away_goals": 0,
                    "avg_total_goals": "",
                    "last5": "",
                    "meetings_json": "[]",
                    "quality": "DEFERRED_BUDGET",
                }
            )
            continue

        payload = client.h2h_events(mapping.event_id)
        h2h_calls += 1
        meetings = normalize_h2h_events(
            payload,
            current_home_team_id=mapping.home_team_id,
            current_away_team_id=mapping.away_team_id,
            current_kickoff=fixture.kickoff,
        )
        summary = summarize_h2h(meetings)
        output.append(
            {
                **base,
                **{k: v for k, v in summary.items() if k != "meetings"},
                "avg_total_goals": (
                    "" if summary["avg_total_goals"] is None else f"{summary['avg_total_goals']:.2f}"
                ),
                "meetings_json": json.dumps(meetings, ensure_ascii=False, separators=(",", ":")),
            }
        )

    output.sort(key=lambda row: (row["kickoff_hkt"], row["hkjc_event_id"]))
    return output


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    ap.add_argument("--max-h2h-events", type=int, default=MAX_H2H_EVENTS)
    args = ap.parse_args()

    rows = read_csv(Path(args.input))
    if not rows:
        raise SystemExit(f"no HKJC fixture rows in {args.input}")

    client = SofascoreClient()
    output = build_sofascore_h2h(
        rows,
        client=client,
        max_h2h_events=max(0, args.max_h2h_events),
    )
    write_csv(Path(args.output), output)

    counts: dict[str, int] = {}
    for row in output:
        key = _clean(row.get("quality")) or "UNKNOWN"
        counts[key] = counts.get(key, 0) + 1
    print(
        "SOFASCORE_H2H "
        f"fixtures={len(output)} "
        + " ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
