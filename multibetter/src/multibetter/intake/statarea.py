from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
import re
import unicodedata
from typing import Mapping, Sequence

from .common import (
    base_row,
    clean_text,
    fetch_soup,
    make_session,
    merge_rows,
    normalize_time,
    pct_text,
)


def _team_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", clean_text(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _parse_date(value: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean_text(value), fmt).date()
        except ValueError:
            pass
    return None


def _clock_datetime(day: date, value: str) -> datetime | None:
    normalized = normalize_time(value)
    if normalized is None:
        return None
    hh, mm = map(int, normalized.split(":"))
    return datetime(day.year, day.month, day.day, hh, mm)


def infer_statarea_clock_offset(
    raw_rows: Sequence[Mapping[str, str]],
    anchor_rows: Sequence[Mapping[str, str]],
    *,
    min_samples: int = 3,
    dominance_ratio: float = 0.80,
) -> tuple[int | None, dict[str, object]]:
    """Infer Statarea's per-run clock offset from known Forebet fixtures.

    Offset definition:
        Statarea raw datetime - canonical anchor UTC datetime, in minutes.

    Only exact oriented team-pair anchors are used. A dominant offset is
    accepted only with enough observations and a strong single-mode majority.
    """

    anchors: dict[tuple[str, str], list[tuple[date, str]]] = {}
    for row in anchor_rows:
        d = _parse_date(str(row.get("DATE", "") or ""))
        t = normalize_time(str(row.get("TIME", "") or ""))
        home = _team_key(str(row.get("HOME TEAM", "") or ""))
        away = _team_key(str(row.get("AWAY TEAM", "") or ""))
        if d and t and home and away:
            anchors.setdefault((home, away), []).append((d, t))

    offsets: list[int] = []
    used_pairs: list[str] = []

    for row in raw_rows:
        source_day = _parse_date(str(row.get("SOURCE_DATE", "") or row.get("DATE", "") or ""))
        source_time = normalize_time(str(row.get("SOURCE_TIME", "") or row.get("TIME", "") or ""))
        home = _team_key(str(row.get("HOME TEAM", "") or ""))
        away = _team_key(str(row.get("AWAY TEAM", "") or ""))
        if not source_day or not source_time or not home or not away:
            continue

        candidates = anchors.get((home, away), ())
        if not candidates:
            continue

        source_dt = _clock_datetime(source_day, source_time)
        if source_dt is None:
            continue

        # Pick the anchor occurrence closest in absolute time. This handles
        # midnight/date rollover without guessing a timezone.
        best: tuple[int, date, str] | None = None
        for anchor_day, anchor_time in candidates:
            anchor_dt = _clock_datetime(anchor_day, anchor_time)
            if anchor_dt is None:
                continue
            diff = int((source_dt - anchor_dt).total_seconds() // 60)
            # Football source clocks should not differ by more than 12 hours
            # for a same-day fixture. Ignore pathological duplicate pair hits.
            if abs(diff) > 720:
                continue
            if best is None or abs(diff) < abs(best[0]):
                best = (diff, anchor_day, anchor_time)

        if best is not None:
            offsets.append(best[0])
            used_pairs.append(f"{home}|{away}")

    counts = Counter(offsets)
    if not counts:
        return None, {
            "samples": 0,
            "dominant_samples": 0,
            "dominance": 0.0,
            "offset_distribution": {},
            "reason": "NO_EXACT_PAIR_ANCHORS",
        }

    offset, dominant = counts.most_common(1)[0]
    dominance = dominant / len(offsets)
    meta = {
        "samples": len(offsets),
        "dominant_samples": dominant,
        "dominance": round(dominance, 4),
        "offset_distribution": dict(sorted(counts.items())),
        "inferred_source_minus_utc_minutes": offset,
        "reason": "",
    }

    if len(offsets) < min_samples:
        meta["reason"] = "INSUFFICIENT_CALIBRATION_SAMPLES"
        return None, meta
    if dominance < dominance_ratio:
        meta["reason"] = "AMBIGUOUS_CLOCK_OFFSET"
        return None, meta

    meta["reason"] = "DOMINANT_EXACT_PAIR_CLOCK_OFFSET"
    return offset, meta


def _apply_clock_offset(
    raw_rows: Sequence[Mapping[str, str]],
    source_minus_utc_minutes: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for raw in raw_rows:
        source_day = _parse_date(str(raw.get("SOURCE_DATE", "") or raw.get("DATE", "") or ""))
        source_time = normalize_time(str(raw.get("SOURCE_TIME", "") or raw.get("TIME", "") or ""))
        if source_day is None or source_time is None:
            continue

        source_dt = _clock_datetime(source_day, source_time)
        if source_dt is None:
            continue

        canonical = source_dt - timedelta(minutes=source_minus_utc_minutes)
        row = dict(raw)
        row["DATE"] = canonical.strftime("%d/%m/%Y")
        row["TIME"] = canonical.strftime("%H:%M")
        row["TIMEZONE"] = (
            "DYNAMIC_OFFSET:"
            f"source-utc={source_minus_utc_minutes:+d}m"
        )
        rows.append(row)

    return rows


def collect_statarea(
    target_dates: Sequence[date],
    *,
    anchor_rows: Sequence[Mapping[str, str]] | None = None,
    timeout: int = 20,
):
    session = make_session()
    raw_rows: list[dict[str, str]] = []
    requests_count = 0
    errors = 0

    for day in target_dates:
        url = f"https://www.statarea.com/predictions/date/{day.isoformat()}/competition"
        try:
            soup = fetch_soup(session, url, timeout=timeout)
            requests_count += 1
        except Exception:
            errors += 1
            continue

        for match in soup.find_all("div", class_="match"):
            try:
                time_box = match.find("div", class_="date")
                host = match.find("div", class_="hostteam")
                guest = match.find("div", class_="guestteam")
                if not time_box or not host or not guest:
                    continue

                host_name = host.find("div", class_="name")
                guest_name = guest.find("div", class_="name")
                info = match.find("div", class_="inforow")
                coefrow = info.find("div", class_="coefrow") if info else None
                if not host_name or not guest_name or not coefrow:
                    continue

                values = []
                for box in coefrow.find_all("div", class_="coefbox"):
                    value_box = box.find("div", class_="value")
                    if value_box:
                        values.append(clean_text(value_box.get_text(" ", strip=True)))
                if len(values) < 11:
                    continue

                source_time = clean_text(time_box.get_text(" ", strip=True))
                if normalize_time(source_time) is None:
                    continue

                # Store source display clock unchanged first. It is calibrated
                # against known Forebet anchors after the page is parsed.
                row = base_row(
                    source="STA",
                    match_date=day,
                    match_time_utc=source_time,
                    home=clean_text(host_name.get_text(" ", strip=True)),
                    away=clean_text(guest_name.get_text(" ", strip=True)),
                    source_url=url,
                    source_date=day.isoformat(),
                    source_time=source_time,
                    timezone_name="UNCALIBRATED_SOURCE_CLOCK",
                    home_away_explicit=True,
                )
                row["HOME PER"] = values[0]
                row["DRAW PER"] = values[1]
                row["AWAY PER"] = values[2]
                row["OVER 1.5"] = values[6]
                row["OVER 2.5"] = values[7]
                row["UNDER 2.5"] = pct_text(100.0 - float(values[7]))
                row["BTS"] = values[9]
                row["OTS"] = values[10]
                raw_rows.append(row)
            except Exception:
                errors += 1

    if not raw_rows:
        return [], requests_count, errors, {
            "samples": 0,
            "reason": "NO_STATAREA_ROWS",
        }

    if not anchor_rows:
        return [], requests_count, errors + 1, {
            "samples": 0,
            "reason": "MISSING_FOREBET_ANCHORS",
        }

    offset, calibration = infer_statarea_clock_offset(raw_rows, anchor_rows)
    if offset is None:
        return [], requests_count, errors + 1, calibration

    rows = _apply_clock_offset(raw_rows, offset)
    return merge_rows(rows), requests_count, errors, calibration
