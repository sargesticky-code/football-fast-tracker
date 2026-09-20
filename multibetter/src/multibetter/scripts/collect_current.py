from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from multibetter.intake import (
    collect_accumulator,
    collect_betclan,
    collect_footballsupertips,
    collect_forebet_from_our_feed,
    collect_primatips,
    collect_statarea,
)
from multibetter.intake.common import (
    SourceHealth,
    preserve_last_good,
    write_health,
)


def _target_dates(start: date, days: int):
    return tuple(start + timedelta(days=i) for i in range(days))


def _run_source(name, func, target_dates, output_dir, health_dir):
    started = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    path = output_dir / {
        "ACC": "accumulator.csv",
        "BCL": "betclan.csv",
        "FST": "footballsupertips.csv",
        "PRE": "prematips.csv",
        "STA": "statarea.csv",
    }[name]
    try:
        rows, requests_count, errors = func(target_dates)
        wrote = preserve_last_good(path, rows)
        status = "OK" if wrote else ("KEEP_LAST_GOOD" if path.exists() else "NO_DATA")
        note = "" if wrote else "No new rows; previous snapshot preserved when available."
    except Exception as exc:
        rows, requests_count, errors = [], 0, 1
        status = "FETCH_ERROR_KEEP_LAST_GOOD" if path.exists() else "FETCH_ERROR"
        note = f"{type(exc).__name__}: {exc}"

    finished = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    health = SourceHealth(
        source=name,
        status=status,
        rows=len(rows),
        requests=requests_count,
        errors=errors,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        note=note,
        target_start=target_dates[0].isoformat(),
        target_end=target_dates[-1].isoformat(),
    )
    write_health(health_dir / f"{name.lower()}.json", health)
    return health


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument(
        "--our-forebet",
        type=Path,
        default=Path("data/forebet_current.csv"),
    )
    parser.add_argument(
        "--our-forebet-supplement",
        type=Path,
        default=Path("data/forebet_supplement_current.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("multibetter/incoming/current"),
    )
    parser.add_argument(
        "--health-dir",
        type=Path,
        default=Path("multibetter/incoming/health"),
    )
    args = parser.parse_args()

    if args.days < 1 or args.days > 3:
        raise SystemExit("--days must be between 1 and 3")

    hkt_today = datetime.now(ZoneInfo("Asia/Hong_Kong")).date()
    start = date.fromisoformat(args.start_date) if args.start_date else hkt_today
    targets = _target_dates(start, args.days)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.health_dir.mkdir(parents=True, exist_ok=True)

    # Forebet is reused from OUR mature production collector rather than opening
    # a second Playwright browser job.
    started = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    forebet_rows = collect_forebet_from_our_feed(
        args.our_forebet,
        supplement_path=args.our_forebet_supplement,
        target_dates=targets,
    )
    forebet_path = args.output_dir / "forebet.csv"
    forebet_wrote = preserve_last_good(forebet_path, forebet_rows)
    forebet_status = (
        "OK"
        if forebet_wrote
        else ("KEEP_LAST_GOOD" if forebet_path.exists() else "NO_DATA")
    )
    forebet_health = SourceHealth(
        source="FRB",
        status=forebet_status,
        rows=len(forebet_rows),
        requests=0,
        errors=0 if forebet_rows else 1,
        started_at=started.isoformat(),
        finished_at=datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        note="Reused OUR Forebet production feed; kickoff normalized from HKJC HKT to UTC.",
        target_start=targets[0].isoformat(),
        target_end=targets[-1].isoformat(),
    )
    write_health(args.health_dir / "frb.json", forebet_health)

    health = [forebet_health]
    health.append(_run_source("ACC", collect_accumulator, targets, args.output_dir, args.health_dir))
    health.append(_run_source("BCL", collect_betclan, targets, args.output_dir, args.health_dir))
    health.append(_run_source("FST", collect_footballsupertips, targets, args.output_dir, args.health_dir))
    health.append(_run_source("PRE", collect_primatips, targets, args.output_dir, args.health_dir))
    health.append(_run_source("STA", collect_statarea, targets, args.output_dir, args.health_dir))

    summary = {
        "built_at_hkt": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        "target_start": targets[0].isoformat(),
        "target_end": targets[-1].isoformat(),
        "sources": {
            item.source: {
                "status": item.status,
                "rows": item.rows,
                "requests": item.requests,
                "errors": item.errors,
                "note": item.note,
            }
            for item in health
        },
    }
    (args.health_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))

    # Forebet is the required anchor. Optional-source failures stay isolated.
    if forebet_status not in {"OK", "KEEP_LAST_GOOD"}:
        raise SystemExit("Required Forebet anchor is unavailable")


if __name__ == "__main__":
    main()
