"""Normalize Forebet score-like fields so Google Sheets keeps them as text.

IMPORTDATA can coerce values such as 1-1 into dates.  This generic post-processing
step rewrites all Forebet predicted-score fields to `1 - 1` before the CSV is
archived or imported into Fast Tracker.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENT = ROOT / "data" / "forebet_current.csv"
SCORE_FIELDS = ("predicted_score", "ou_predicted_score", "corner_predicted_score")
SCORE_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


def normalize(value: str) -> str:
    value = (value or "").strip()
    m = SCORE_RE.match(value)
    return f"{m.group(1)} - {m.group(2)}" if m else value


def main() -> int:
    if not CURRENT.exists():
        raise SystemExit(f"missing {CURRENT}")
    with CURRENT.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    changed = 0
    for row in rows:
        for field in SCORE_FIELDS:
            if field not in fields:
                continue
            old = row.get(field, "")
            new = normalize(old)
            if new != old:
                row[field] = new
                changed += 1
    tmp = CURRENT.with_suffix(".text.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(CURRENT)
    print(f"FOREBET_TEXT_NORMALIZE rows={len(rows)} changed={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
