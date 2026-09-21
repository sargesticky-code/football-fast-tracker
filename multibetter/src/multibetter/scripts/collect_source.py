from __future__ import annotations

import argparse
import csv
import json
import signal
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
from multibetter.intake.common import SourceHealth, preserve_last_good, write_health


FILES = {
    "FRB": "forebet.csv",
    "ACC": "accumulator.csv",
    "BCL": "betclan.csv",
    "FST": "footballsupertips.csv",
    "PRE": "prematips.csv",
    "STA": "statarea.csv",
}

COLLECTORS = {
    "ACC": collect_accumulator,
    "BCL": collect_betclan,
    "FST": collect_footballsupertips,
    "PRE": collect_primatips,
    "STA": collect_statarea,
}


class SourceDeadline(BaseException):
    pass


def _deadline_handler(signum, frame):
    raise SourceDeadline("source runtime limit exceeded")


def target_dates(start: date, days: int):
    return tuple(start + timedelta(days=i) for i in range(days))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=sorted(FILES), required=True)
    parser.add_argument("--start-date")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--max-seconds", type=int, default=150)
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
        "--anchor-file",
        type=Path,
        default=Path("multibetter/incoming/current/forebet.csv"),
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

    hkt_today = datetime.now(ZoneInfo("Asia/Hong_Kong")).date()
    start = date.fromisoformat(args.start_date) if args.start_date else hkt_today
    targets = target_dates(start, args.days)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.health_dir.mkdir(parents=True, exist_ok=True)

    output = args.output_dir / FILES[args.source]
    started = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    rows = []
    requests_count = 0
    errors = 0
    status = "NO_DATA"
    note = ""

    old_handler = signal.signal(signal.SIGALRM, _deadline_handler)
    signal.setitimer(signal.ITIMER_REAL, max(1, args.max_seconds))

    try:
        if args.source == "FRB":
            rows = collect_forebet_from_our_feed(
                args.our_forebet,
                supplement_path=args.our_forebet_supplement,
                target_dates=targets,
            )
            note = (
                "Reused OUR Forebet production feed; kickoff normalized "
                "from HKJC HKT to UTC."
            )
        else:
            kwargs = {}
            anchor_rows = []
            if args.anchor_file.exists():
                with args.anchor_file.open(
                    "r", encoding="utf-8-sig", newline=""
                ) as fh:
                    anchor_rows = list(csv.DictReader(fh))

            if args.source in {"ACC", "BCL"}:
                kwargs["target_pairs"] = [
                    (row.get("HOME TEAM", ""), row.get("AWAY TEAM", ""))
                    for row in anchor_rows
                ]
            elif args.source == "STA":
                kwargs["anchor_rows"] = anchor_rows

            collected = COLLECTORS[args.source](targets, **kwargs)
            if len(collected) == 4:
                rows, requests_count, errors, metadata = collected
                if metadata:
                    note = "calibration=" + json.dumps(
                        metadata,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
            else:
                rows, requests_count, errors = collected

        wrote = preserve_last_good(output, rows)
        status = (
            "OK"
            if wrote
            else ("KEEP_LAST_GOOD" if output.exists() else "NO_DATA")
        )
        if not wrote and not note:
            note = "No new rows; previous snapshot preserved when available."
    except SourceDeadline:
        errors += 1
        status = "TIMEOUT_KEEP_LAST_GOOD" if output.exists() else "TIMEOUT"
        note = f"Source exceeded overall {args.max_seconds}s runtime limit."
    except Exception as exc:
        errors += 1
        status = (
            "FETCH_ERROR_KEEP_LAST_GOOD"
            if output.exists()
            else "FETCH_ERROR"
        )
        note = f"{type(exc).__name__}: {exc}"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)

    health = SourceHealth(
        source=args.source,
        status=status,
        rows=len(rows),
        requests=requests_count,
        errors=errors,
        started_at=started.isoformat(),
        finished_at=datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        note=note,
        target_start=targets[0].isoformat(),
        target_end=targets[-1].isoformat(),
    )
    write_health(args.health_dir / f"{args.source.lower()}.json", health)
    print(json.dumps(health.__dict__, ensure_ascii=False))

    # HKJC is the canonical fixture universe. FRB is an evidence source.
    # Any provider may fail closed into health metadata without blocking the
    # other independent sources.


if __name__ == "__main__":
    main()
