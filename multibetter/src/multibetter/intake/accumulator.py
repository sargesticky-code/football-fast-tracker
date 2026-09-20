from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
from typing import Sequence

from .common import (
    base_row,
    clean_text,
    fetch_soup,
    make_session,
    merge_rows,
    local_fixture_to_utc,
    pct_text,
    resolve_partial_date,
)


ROOT = "https://www.accagenerator.com/football-predictions/"


def _market_url(base: str, suffix: str) -> str:
    return base.rstrip("/") + "/" + suffix.strip("/") + "/"


def _split_teams(text: str):
    parts = re.split(r"\s+vs\.?\s+", clean_text(text), maxsplit=1, flags=re.I)
    return parts if len(parts) == 2 else None


def _norm_team(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def _pair_matches_targets(
    home: str,
    away: str,
    target_pairs: Sequence[tuple[str, str]] | None,
    *,
    threshold: float = 0.55,
) -> bool:
    if not target_pairs:
        return True

    home_n = _norm_team(home)
    away_n = _norm_team(away)
    for target_home, target_away in target_pairs:
        th = _norm_team(target_home)
        ta = _norm_team(target_away)
        hs = SequenceMatcher(None, home_n, th).ratio()
        aws = SequenceMatcher(None, away_n, ta).ratio()
        if hs >= threshold and aws >= threshold:
            return True
    return False


def _parse_market_page(
    soup,
    *,
    market: str,
    url: str,
    target_dates: Sequence[date],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

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

        source_time = time_match.group(1)
        converted = local_fixture_to_utc(
            match_date, source_time, "Europe/London"
        )
        if converted is None:
            continue
        match_date_utc, match_time = converted
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
            match_date=match_date_utc,
            match_time_utc=match_time,
            league=league,
            home=home,
            away=away,
            source_url=url,
            source_date=source_date_text,
            source_time=source_time,
            timezone_name="Europe/London",
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

    return rows


def collect_accumulator(
    target_dates: Sequence[date],
    *,
    target_pairs: Sequence[tuple[str, str]] | None = None,
    timeout: int = 20,
    delay_seconds: float = 0.10,
):
    """Collect AccaGenerator efficiently around the current Forebet universe.

    Phase 1 fetches the 1X2 page for every active league route. Only routes
    containing at least one fixture that can match the current oriented
    Forebet target pairs then receive the extra O/U and BTTS requests.

    This keeps target coverage while avoiding 3x requests for irrelevant
    leagues.
    """

    session = make_session()
    root = fetch_soup(session, ROOT, timeout=timeout)
    links = []
    for anchor in root.find_all("a", href=True):
        href = anchor["href"]
        if href.startswith(
            "https://www.accagenerator.com/football-tips-and-predictions-for"
        ) and href not in links:
            links.append(href)

    rows: list[dict[str, str]] = []
    requests_count = 1
    errors = 0

    for base in links:
        hda_url = _market_url(base, "1x2-predictions/")
        try:
            soup = fetch_soup(
                session,
                hda_url,
                timeout=timeout,
                delay_seconds=delay_seconds,
            )
            requests_count += 1
        except Exception:
            errors += 1
            continue

        hda_rows = _parse_market_page(
            soup,
            market="1x2",
            url=hda_url,
            target_dates=target_dates,
        )
        rows.extend(hda_rows)

        route_relevant = any(
            _pair_matches_targets(
                row["HOME TEAM"],
                row["AWAY TEAM"],
                target_pairs,
            )
            for row in hda_rows
        )
        if not route_relevant:
            continue

        for market, suffix in (
            ("ou25", "over-under-predictions/"),
            ("btts", "both-teams-score-predictions/"),
        ):
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

            rows.extend(
                _parse_market_page(
                    soup,
                    market=market,
                    url=url,
                    target_dates=target_dates,
                )
            )

    return merge_rows(rows), requests_count, errors
