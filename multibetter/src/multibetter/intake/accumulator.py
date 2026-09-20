from __future__ import annotations

import re
from datetime import date
from typing import Sequence

from .common import (
    base_row,
    clean_text,
    fetch_soup,
    make_session,
    merge_rows,
    pct_text,
    resolve_partial_date,
)


ROOT = "https://www.accagenerator.com/football-predictions/"


def _market_url(base: str, suffix: str) -> str:
    return base.rstrip("/") + "/" + suffix.strip("/") + "/"


def _split_teams(text: str):
    parts = re.split(r"\s+vs\.?\s+", clean_text(text), maxsplit=1, flags=re.I)
    return parts if len(parts) == 2 else None


def collect_accumulator(
    target_dates: Sequence[date],
    *,
    timeout: int = 20,
    delay_seconds: float = 0.15,
):
    session = make_session()
    root = fetch_soup(session, ROOT, timeout=timeout)
    links = []
    for anchor in root.find_all("a", href=True):
        href = anchor["href"]
        if href.startswith(
            "https://www.accagenerator.com/football-tips-and-predictions-for"
        ) and href not in links:
            links.append(href)

    rows = []
    requests_count = 1
    errors = 0

    markets = {
        "1x2": "1x2-predictions/",
        "ou25": "over-under-predictions/",
        "btts": "both-teams-score-predictions/",
    }

    for base in links:
        for market, suffix in markets.items():
            url = _market_url(base, suffix)
            try:
                soup = fetch_soup(
                    session,
                    url,
                    timeout=timeout,
                    delay_seconds=delay_seconds,
                )
                requests_count += 1
            except Exception:
                errors += 1
                continue

            for item in soup.find_all("li"):
                date_box = item.find("div", class_="datecombos")
                teams_box = item.find("h3", class_="tips-card__name-first")
                tip_box = item.find("div", class_="tipdetail")
                pct_box = item.find("span", class_="count-text")
                if not all((date_box, teams_box, tip_box, pct_box)):
                    continue

                source_date_text = clean_text(date_box.get_text(" ", strip=True))
                match_date = resolve_partial_date(source_date_text, target_dates)
                if match_date is None:
                    continue

                time_match = re.search(r"\b(\d{1,2}:\d{2})\b", source_date_text)
                teams = _split_teams(teams_box.get_text(" ", strip=True))
                if not time_match or not teams:
                    continue

                match_time = time_match.group(1)
                home, away = map(clean_text, teams)
                league_box = item.find("span", class_="tips-card__league")
                league = clean_text(
                    league_box.get_text(" ", strip=True) if league_box else ""
                )
                tip = clean_text(tip_box.get_text(" ", strip=True))
                try:
                    probability = float(pct_box.get("data-stop") or "")
                except ValueError:
                    continue

                row = base_row(
                    source="ACC",
                    match_date=match_date,
                    match_time_utc=match_time,
                    league=league,
                    home=home,
                    away=away,
                    source_url=url,
                    source_date=source_date_text,
                    source_time=match_time,
                    timezone_name="GMT",
                    home_away_explicit=True,
                )

                if market == "1x2":
                    residual = max(0.0, 100.0 - probability) / 2.0
                    if tip == "1":
                        h, d, a = probability, residual, residual
                    elif tip == "2":
                        h, d, a = residual, residual, probability
                    elif tip.upper() == "X":
                        h, d, a = residual, probability, residual
                    else:
                        continue
                    row["HOME PER"] = pct_text(h)
                    row["DRAW PER"] = pct_text(d)
                    row["AWAY PER"] = pct_text(a)
                elif market == "ou25":
                    if tip.lower().startswith("over"):
                        over, under = probability, 100.0 - probability
                    elif tip.lower().startswith("under"):
                        under, over = probability, 100.0 - probability
                    else:
                        continue
                    row["OVER 2.5"] = pct_text(over)
                    row["UNDER 2.5"] = pct_text(under)
                else:
                    if tip.lower() == "yes":
                        yes, no = probability, 100.0 - probability
                    elif tip.lower() == "no":
                        no, yes = probability, 100.0 - probability
                    else:
                        continue
                    row["BTS"] = pct_text(yes)
                    row["OTS"] = pct_text(no)
                    row["OVER 1.5"] = pct_text(min(100.0, yes + 15.0))

                rows.append(row)

    return merge_rows(rows), requests_count, errors
