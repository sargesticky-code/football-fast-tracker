from __future__ import annotations

import csv
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import requests
from bs4 import BeautifulSoup


STANDARD_COLUMNS = [
    "DATE", "TIME", "LEAGUE", "HOME TEAM", "AWAY TEAM",
    "HOME PER", "DRAW PER", "AWAY PER",
    "1X PER", "12 PER", "X2 PER",
    "OVER 1.5", "UNDER 2.5", "OVER 2.5",
    "BTS", "OTS", "NAME",
    "SOURCE_URL", "SOURCE_DATE", "SOURCE_TIME",
    "TIMEZONE", "HOME_AWAY_EXPLICIT",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class SourceHealth:
    source: str
    status: str
    rows: int = 0
    requests: int = 0
    errors: int = 0
    started_at: str = ""
    finished_at: str = ""
    note: str = ""
    target_start: str = ""
    target_end: str = ""


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-GB,en;q=0.9",
    })
    return session


def fetch_soup(
    session: requests.Session,
    url: str,
    *,
    timeout: int = 20,
    delay_seconds: float = 0.0,
) -> BeautifulSoup:
    if delay_seconds:
        time.sleep(delay_seconds)
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return BeautifulSoup(response.content, "html.parser")


def clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def number(value: object) -> float | None:
    text = clean_text(value).replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def pct_text(value: float | int | None) -> str:
    if value is None:
        return ""
    value = max(0.0, min(100.0, float(value)))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def normalize_time(value: str) -> str | None:
    match = re.search(r"\b(\d{1,2}):(\d{2})\b", clean_text(value))
    if not match:
        return None
    hh, mm = int(match.group(1)), int(match.group(2))
    if hh > 23 or mm > 59:
        return None
    return f"{hh:02d}:{mm:02d}"


def parse_date_any(value: str, *, default_year: int | None = None) -> date | None:
    text = clean_text(value)
    formats = (
        "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d.%m.%Y",
        "%d.%m.%y", "%Y.%m.%d", "%Y-%m-%dT%H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    match = re.search(
        r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b",
        text,
    )
    if not match:
        return None

    dd, mm = int(match.group(1)), int(match.group(2))
    year_text = match.group(3)
    if year_text:
        yy = int(year_text)
        year = yy + 2000 if yy < 100 else yy
    elif default_year:
        year = default_year
    else:
        return None
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


def resolve_partial_date(text: str, target_dates: Sequence[date]) -> date | None:
    # Prefer an explicit year when available.
    explicit = parse_date_any(text)
    if explicit and explicit in target_dates:
        return explicit

    match = re.search(r"\b(\d{1,2})[./-](\d{1,2})\b", clean_text(text))
    if not match:
        return None
    dd, mm = int(match.group(1)), int(match.group(2))
    hits = [d for d in target_dates if d.day == dd and d.month == mm]
    return hits[0] if len(hits) == 1 else None


def fmt_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def utc_from_hkt(value: str) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None

    parsed = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text[:19], fmt)
            break
        except ValueError:
            pass

    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def add_double_chance(row: dict[str, str]) -> None:
    home = number(row.get("HOME PER"))
    draw = number(row.get("DRAW PER"))
    away = number(row.get("AWAY PER"))
    if None in (home, draw, away):
        return
    row["1X PER"] = pct_text(home + draw)
    row["12 PER"] = pct_text(home + away)
    row["X2 PER"] = pct_text(draw + away)


def base_row(
    *,
    source: str,
    match_date: date,
    match_time_utc: str,
    home: str,
    away: str,
    league: str = "",
    source_url: str = "",
    source_date: str = "",
    source_time: str = "",
    timezone_name: str = "UTC",
    home_away_explicit: bool = True,
) -> dict[str, str]:
    row = {column: "" for column in STANDARD_COLUMNS}
    row.update({
        "DATE": fmt_date(match_date),
        "TIME": match_time_utc,
        "LEAGUE": clean_text(league),
        "HOME TEAM": clean_text(home),
        "AWAY TEAM": clean_text(away),
        "NAME": source,
        "SOURCE_URL": source_url,
        "SOURCE_DATE": source_date or fmt_date(match_date),
        "SOURCE_TIME": source_time or match_time_utc,
        "TIMEZONE": timezone_name,
        "HOME_AWAY_EXPLICIT": "1" if home_away_explicit else "0",
    })
    return row


def merge_rows(rows: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    state: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for raw in rows:
        row = {column: clean_text(raw.get(column, "")) for column in STANDARD_COLUMNS}
        key = (row["DATE"], row["TIME"], row["HOME TEAM"], row["AWAY TEAM"])
        if not all(key):
            continue
        current = state.setdefault(key, {column: "" for column in STANDARD_COLUMNS})
        for column, value in row.items():
            if value not in ("", None):
                current[column] = str(value)
    for row in state.values():
        add_double_chance(row)
    return sorted(
        state.values(),
        key=lambda r: (r["DATE"], r["TIME"], r["HOME TEAM"], r["AWAY TEAM"]),
    )


def write_csv_atomic(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        delete=False,
    ) as fh:
        temp_name = fh.name
        writer = csv.DictWriter(fh, fieldnames=STANDARD_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in STANDARD_COLUMNS})
    os.replace(temp_name, path)


def write_health(path: Path, health: SourceHealth) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(health), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def preserve_last_good(
    current_path: Path,
    rows: Sequence[Mapping[str, object]],
) -> bool:
    """Write only non-empty source snapshots. Empty runs keep the prior file."""
    if not rows:
        return False
    write_csv_atomic(current_path, rows)
    return True
