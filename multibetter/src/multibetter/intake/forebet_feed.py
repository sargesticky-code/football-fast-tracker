from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Sequence

from .common import (
    add_double_chance,
    base_row,
    clean_text,
    merge_rows,
    number,
    pct_text,
    utc_from_hkt,
)


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def collect_forebet_from_our_feed(
    current_path: Path,
    *,
    supplement_path: Path | None = None,
    target_dates: Sequence[date],
) -> list[dict[str, str]]:
    """Convert OUR mature Forebet feed into the GitHub-multi standard schema.

    Matching time is normalized to UTC from HKJC HKT. The original Forebet
    source time remains in SOURCE_TIME for audit.
    """

    supplement_by_event = {}
    if supplement_path:
        for row in _read(supplement_path):
            event_id = clean_text(row.get("hkjc_event_id"))
            if event_id:
                supplement_by_event[event_id] = row

    rows = []
    for raw in _read(current_path):
        event_id = clean_text(raw.get("hkjc_event_id"))
        utc_dt = utc_from_hkt(raw.get("hkjc_kickoff_hkt", ""))
        if utc_dt is None or utc_dt.date() not in target_dates:
            continue

        source_time = ""
        kickoff_text = clean_text(raw.get("kickoff_text"))
        if kickoff_text:
            parts = kickoff_text.rsplit(" ", 1)
            if len(parts) == 2:
                source_time = parts[1]

        row = base_row(
            source="FRB",
            match_date=utc_dt.date(),
            match_time_utc=utc_dt.strftime("%H:%M"),
            league=clean_text(raw.get("league_short")),
            home=clean_text(raw.get("home_team")),
            away=clean_text(raw.get("away_team")),
            source_url=clean_text(raw.get("forebet_detail_url")),
            source_date=clean_text(raw.get("match_date")),
            source_time=source_time,
            timezone_name="UTC(normalized from HKJC HKT)",
            home_away_explicit=True,
        )

        row["HOME PER"] = pct_text(number(raw.get("prob_home")))
        row["DRAW PER"] = pct_text(number(raw.get("prob_draw")))
        row["AWAY PER"] = pct_text(number(raw.get("prob_away")))

        supplement = supplement_by_event.get(event_id, {})
        over = number(raw.get("prob_over25"))
        under = number(raw.get("prob_under25"))
        if over is None:
            over = number(supplement.get("prob_over25"))
        if under is None:
            under = number(supplement.get("prob_under25"))
        row["OVER 2.5"] = pct_text(over)
        row["UNDER 2.5"] = pct_text(under)
        add_double_chance(row)
        rows.append(row)

    return merge_rows(rows)
