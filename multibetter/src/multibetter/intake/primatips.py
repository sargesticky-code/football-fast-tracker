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


def _urls(day: date):
    token = day.isoformat()
    base = f"https://primatips.com/tips/{token}"
    return {
        "hda": base,
        "ou25": base + "/over-under-25",
        "btts": base + "/both-teams-to-score",
    }


def collect_primatips(
    target_dates: Sequence[date],
    *,
    timeout: int = 20,
):
    session = make_session()
    rows = []
    requests_count = 0
    errors = 0

    for day in target_dates:
        by_market = {}
        for market, url in _urls(day).items():
            try:
                soup = fetch_soup(session, url, timeout=timeout)
                requests_count += 1
            except Exception:
                errors += 1
                by_market[market] = []
                continue

            teams = [
                clean_text(x.get_text(" ", strip=True))
                for x in soup.find_all("span", class_="nms")
            ]
            parsed_teams = []
            for item in teams:
                if "-" not in item:
                    continue
                home, away = item.split("-", 1)
                parsed_teams.append((clean_text(home), clean_text(away)))

            market_rows = []
            if market == "hda":
                times = [
                    clean_text(x.get_text(" ", strip=True))
                    for x in soup.find_all("span", class_="tm")
                ]
                per = [
                    clean_text(x.get_text(" ", strip=True)).replace("%", "")
                    for x in soup.find_all("span", class_="t")
                ]
                size = min(len(parsed_teams), len(times), len(per) // 3)
                for i in range(size):
                    home, away = parsed_teams[i]
                    converted = local_fixture_to_utc(
                        day, times[i], "Europe/London"
                    )
                    if converted is None:
                        continue
                    match_date_utc, match_time_utc = converted
                    row = base_row(
                        source="PRE",
                        match_date=match_date_utc,
                        match_time_utc=match_time_utc,
                        home=home,
                        away=away,
                        source_url=url,
                        source_date=day.isoformat(),
                        source_time=times[i],
                        timezone_name="Europe/London",
                        home_away_explicit=True,
                    )
                    row["HOME PER"] = per[i * 3]
                    row["DRAW PER"] = per[i * 3 + 1]
                    row["AWAY PER"] = per[i * 3 + 2]
                    market_rows.append(row)
            else:
                per = [
                    clean_text(x.get_text(" ", strip=True)).replace("%", "")
                    for x in soup.find_all("span", class_="t2")
                ]
                size = min(len(parsed_teams), len(per) // 2)
                for i in range(size):
                    home, away = parsed_teams[i]
                    row = base_row(
                        source="PRE",
                        match_date=day,
                        match_time_utc="00:00",
                        home=home,
                        away=away,
                        source_url=url,
                        timezone_name="UTC/GMT assumed from upstream compatibility",
                        home_away_explicit=True,
                    )
                    if market == "ou25":
                        row["OVER 2.5"] = per[i * 2]
                        row["UNDER 2.5"] = per[i * 2 + 1]
                    else:
                        row["BTS"] = per[i * 2]
                        row["OTS"] = per[i * 2 + 1]
                    market_rows.append(row)
            by_market[market] = market_rows

        ou = {
            (r["HOME TEAM"], r["AWAY TEAM"]): r
            for r in by_market.get("ou25", [])
        }
        btts = {
            (r["HOME TEAM"], r["AWAY TEAM"]): r
            for r in by_market.get("btts", [])
        }
        for row in by_market.get("hda", []):
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
