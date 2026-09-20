from __future__ import annotations

from datetime import date
from typing import Sequence

from .common import (
    base_row,
    clean_text,
    fetch_soup,
    make_session,
    merge_rows,
    parse_date_any,
    pct_text,
)


URLS = {
    "today": {
        "hda": "https://www.footballsuper.tips/todays-free-football-super-tips/",
        "ou25": "https://www.footballsuper.tips/todays-over-under-football-super-tips/",
        "btts": "https://www.footballsuper.tips/todays-both-teams-to-score-football-super-tips/",
    },
    "tomorrow": {
        "hda": "https://www.footballsuper.tips/tomorrows-free-football-super-tips/",
        "ou25": "https://www.footballsuper.tips/tomorrows-over-under-football-super-tips/",
        "btts": "https://www.footballsuper.tips/tomorrows-both-teams-to-score-football-super-tips/",
    },
}


def _rows_from_page(soup, market: str, url: str, target_dates: Sequence[date]):
    homes = [clean_text(x.get_text(" ", strip=True)) for x in soup.find_all("div", class_="homedisp")]
    aways = [clean_text(x.get_text(" ", strip=True)) for x in soup.find_all("div", class_="awaydisp")]
    percs = [clean_text(x.get_text(" ", strip=True)).split() for x in soup.find_all("div", class_="percdiv")]

    if market == "hda":
        dates = [clean_text(x.get_text(" ", strip=True)) for x in soup.find_all("div", class_="datedisp")]
        size = min(len(homes), len(aways), len(percs), len(dates))
    else:
        dates = []
        size = min(len(homes), len(aways), len(percs))

    rows = []
    for i in range(size):
        if market == "hda":
            parts = dates[i].split()
            if len(parts) < 2:
                continue
            match_date = parse_date_any(parts[0])
            match_time = parts[1]
            if match_date not in target_dates:
                continue
        else:
            # Market pages do not need their own date/time because they merge
            # into the HDA fixture by oriented team pair later.
            match_date = target_dates[0]
            match_time = "00:00"

        row = base_row(
            source="FST",
            match_date=match_date,
            match_time_utc=match_time,
            home=homes[i],
            away=aways[i],
            source_url=url,
            source_date="" if market != "hda" else parts[0],
            source_time="" if market != "hda" else match_time,
            timezone_name="UTC/GMT",
            home_away_explicit=True,
        )

        values = [x.replace("%", "") for x in percs[i]]
        if market == "hda" and len(values) >= 3:
            row["HOME PER"], row["DRAW PER"], row["AWAY PER"] = values[:3]
        elif market == "ou25" and len(values) >= 2:
            row["OVER 2.5"], row["UNDER 2.5"] = values[:2]
        elif market == "btts" and len(values) >= 2:
            row["BTS"], row["OTS"] = values[:2]
        rows.append(row)
    return rows


def collect_footballsupertips(
    target_dates: Sequence[date],
    *,
    timeout: int = 20,
):
    session = make_session()
    rows = []
    requests_count = 0
    errors = 0

    # Fetch both today and tomorrow pages. Final date filtering is driven by HDA.
    market_rows = {}
    for bucket in ("today", "tomorrow"):
        for market, url in URLS[bucket].items():
            try:
                soup = fetch_soup(session, url, timeout=timeout)
                requests_count += 1
                market_rows[(bucket, market)] = _rows_from_page(
                    soup,
                    market,
                    url,
                    target_dates,
                )
            except Exception:
                errors += 1
                market_rows[(bucket, market)] = []

    # Build HDA fixtures first, then attach O/U and BTTS by oriented pair within
    # the same today/tomorrow page bucket.
    for bucket in ("today", "tomorrow"):
        hda = market_rows[(bucket, "hda")]
        ou = {
            (r["HOME TEAM"], r["AWAY TEAM"]): r
            for r in market_rows[(bucket, "ou25")]
        }
        btts = {
            (r["HOME TEAM"], r["AWAY TEAM"]): r
            for r in market_rows[(bucket, "btts")]
        }
        for row in hda:
            key = (row["HOME TEAM"], row["AWAY TEAM"])
            for extra in (ou.get(key), btts.get(key)):
                if not extra:
                    continue
                for field in ("OVER 2.5", "UNDER 2.5", "BTS", "OTS"):
                    if extra.get(field):
                        row[field] = extra[field]
            if row.get("BTS"):
                row["OVER 1.5"] = pct_text(
                    min(100.0, float(row["BTS"]) + 15.0)
                )
            rows.append(row)

    return merge_rows(rows), requests_count, errors
