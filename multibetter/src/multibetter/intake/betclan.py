from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse
from datetime import date
from typing import Sequence

from .common import (
    base_row,
    clean_text,
    fetch_soup,
    make_session,
    merge_rows,
    local_fixture_to_utc,
    parse_date_any,
    pct_text,
)


INDEX_URLS = (
    "https://www.betclan.com/todays-football-predictions/",
    "https://www.betclan.com/tomorrows-football-predictions/",
)


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def _fixture_slug(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    slug = slug.split("-prediction", 1)[0]
    return _normalize_name(slug.replace("-v-", " vs ").replace("-", " "))


def _targeted_links(
    links: Sequence[str],
    target_pairs: Sequence[tuple[str, str]] | None,
    *,
    threshold: float = 0.58,
) -> list[str]:
    if not target_pairs:
        return list(links)

    targets = [
        _normalize_name(f"{home} vs {away}")
        for home, away in target_pairs
        if home and away
    ]
    selected = []
    for link in links:
        slug = _fixture_slug(link)
        if not slug:
            continue
        best = max(
            (SequenceMatcher(None, slug, target).ratio() for target in targets),
            default=0.0,
        )
        if best >= threshold:
            selected.append(link)
    return selected


def collect_betclan(
    target_dates: Sequence[date],
    *,
    target_pairs: Sequence[tuple[str, str]] | None = None,
    timeout: int = 20,
    delay_seconds: float = 0.10,
):
    session = make_session()
    links = []
    requests_count = 0
    errors = 0

    for index_url in INDEX_URLS:
        try:
            soup = fetch_soup(session, index_url, timeout=timeout)
            requests_count += 1
        except Exception:
            errors += 1
            continue
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if href.startswith("https://www.betclan.com/predictionsdetails/") and href not in links:
                links.append(href)

    links = _targeted_links(links, target_pairs)

    rows = []
    for url in links:
        try:
            soup = fetch_soup(
                session,
                url,
                timeout=timeout,
                delay_seconds=delay_seconds,
            )
            requests_count += 1

            stats = [
                clean_text(x.get_text(" ", strip=True)).replace("%", "").split()
                for x in soup.find_all(
                    "div",
                    class_="cell vote__stats js-vote-stats-container",
                )
            ]
            date_box = soup.find("span", class_="dategamedetailsis")
            teams_box = soup.find("div", class_="teamstop")
            if len(stats) < 3 or not date_box or not teams_box:
                raise ValueError("missing BetClan prediction structure")

            date_text = clean_text(date_box.get_text(" ", strip=True))
            match_date = parse_date_any(date_text)
            time_match = re.search(r"\b(\d{1,2}:\d{2})\b", date_text)
            if match_date not in target_dates or not time_match:
                continue

            source_time = time_match.group(1)
            converted = local_fixture_to_utc(
                match_date, source_time, "Europe/London"
            )
            if converted is None:
                continue
            match_date_utc, match_time = converted

            teams = [
                clean_text(x)
                for x in teams_box.get_text("\n", strip=True).split("\n")
                if clean_text(x)
            ]
            if len(teams) < 2:
                continue

            # Upstream structure: Home <pct> Draw <pct> Away <pct>, etc.
            h = float(stats[0][1])
            d = float(stats[0][3])
            a = float(stats[0][5])
            under = float(stats[1][1])
            over = float(stats[1][3])
            bts = float(stats[2][1])
            ots = float(stats[2][3])

            row = base_row(
                source="BCL",
                match_date=match_date_utc,
                match_time_utc=match_time,
                home=teams[0],
                away=teams[-1],
                source_url=url,
                source_date=date_text,
                source_time=source_time,
                timezone_name="Europe/London",
                home_away_explicit=True,
            )
            row["HOME PER"] = pct_text(h)
            row["DRAW PER"] = pct_text(d)
            row["AWAY PER"] = pct_text(a)
            row["UNDER 2.5"] = pct_text(under)
            row["OVER 2.5"] = pct_text(over)
            row["BTS"] = pct_text(bts)
            row["OTS"] = pct_text(ots)
            row["OVER 1.5"] = pct_text(min(100.0, bts + 15.0))
            rows.append(row)
        except Exception:
            errors += 1

    return merge_rows(rows), requests_count, errors
