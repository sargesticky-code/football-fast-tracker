from __future__ import annotations

from datetime import date
from typing import Sequence

from .common import (
    base_row,
    clean_text,
    fetch_soup,
    make_session,
    merge_rows,
    local_fixture_to_utc,
    pct_text,
)


def collect_statarea(
    target_dates: Sequence[date],
    *,
    timeout: int = 20,
):
    session = make_session()
    rows = []
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
                converted = local_fixture_to_utc(
                    day, source_time, "Europe/Berlin"
                )
                if converted is None:
                    continue
                match_date_utc, match_time_utc = converted

                row = base_row(
                    source="STA",
                    match_date=match_date_utc,
                    match_time_utc=match_time_utc,
                    home=clean_text(host_name.get_text(" ", strip=True)),
                    away=clean_text(guest_name.get_text(" ", strip=True)),
                    source_url=url,
                    source_date=day.isoformat(),
                    source_time=source_time,
                    timezone_name="Europe/Berlin",
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
                rows.append(row)
            except Exception:
                errors += 1

    return merge_rows(rows), requests_count, errors
