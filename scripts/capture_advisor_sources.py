#!/usr/bin/env python3
"""Bounded, read-only BetClan / SportyTrader capture. Never assigns canonical IDs.

Output is unverified source evidence, NOT bookmaker odds or executable picks.
The repository's verified fixture/alias gate must approve a separate promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

LISTINGS = {
    "BETCLAN": (
        "https://www.betclan.com/todays-football-predictions/",
        "https://www.betclan.com/tomorrows-football-predictions/",
    ),
    "SPORTYTRADER": (
        "https://www.sportytrader.com/en/betting-tips/football/today/",
        "https://www.sportytrader.com/en/betting-tips/football/tomorrow/",
    ),
}
DOMAINS = {"BETCLAN": "www.betclan.com", "SPORTYTRADER": "www.sportytrader.com"}
USER_AGENT = "FastTrackerPersonalResearch/1.0 (low-frequency; source attribution)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html"}
MAX_BYTES = 2_000_000
TIMEOUT = 12


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def num(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
        return parsed if 0 <= parsed <= 100 else None
    except (ValueError, TypeError):
        return None


def extract_links(provider: str, page: str, base: str) -> list[str]:
    soup = BeautifulSoup(page, "html.parser")
    links = []
    for item in soup.select("a[href]"):
        target = urljoin(base, item.get("href", ""))
        parsed = urlparse(target)
        if parsed.scheme != "https" or parsed.hostname != DOMAINS[provider]:
            continue
        path = parsed.path.lower()
        if provider == "BETCLAN":
            eligible = re.fullmatch(r"/predictionsdetails/football/\d+/[^/]+/?", path)
        else:
            eligible = re.fullmatch(r"/en/betting-tips/[^/]+-\d+/?", path)
        if eligible:
            normalized = f"https://{DOMAINS[provider]}{parsed.path}"
            if normalized not in links:
                links.append(normalized)
    return links


def _pct_in(text: str, label: str) -> float | None:
    match = re.search(r"\b" + re.escape(label) + r"\s*(\d{1,3}(?:\.\d+)?)\s*%", text, re.I)
    return num(match.group(1)) if match else None


def _market_text(text: str, heading: str, next_heading: str) -> str:
    m = re.search(r"\b" + heading + r"\b(.*?)\b" + next_heading + r"\b", text, re.I | re.S)
    return m.group(1) if m else ""


def betclan_detail(page: str, url: str) -> dict:
    soup = BeautifulSoup(page, "html.parser")
    heading = clean(soup.h1.get_text(" ", strip=True)) if soup.h1 else ""
    teams = re.search(r"^(.+?)\s+vs\s+(.+?)\s+Prediction\b", heading, re.I)
    if not teams:
        raise ValueError("BETCLAN_MATCH_HEADING_MISSING")
    home, away = clean(teams.group(1)), clean(teams.group(2))
    text = clean(soup.get_text(" ", strip=True))
    # The primary forecast is above team stats / Users Average. Never mix votes.
    main = re.split(r"Team Momentum Performance Ranking|Users Average", text, maxsplit=1, flags=re.I)[0]
    date = re.search(r"\bDate\s+(\d{4}-\d\d-\d\d\s+\d\d:\d\d)\b", main, re.I)
    win = _market_text(main, "Winner", "Total Goals")
    goals = _market_text(main, r"Total Goals\s+2\.5", "Both Teams to Score")
    btts = _market_text(main, r"Both Teams to Score\s+BTTS", "Correct Score")
    score_section = _market_text(main, "Correct Score", "Team Momentum Performance Ranking")
    if not score_section:
        score_section = main.split("Correct Score", 1)[-1][:100] if "Correct Score" in main else ""
    score = re.search(r"\b(\d{1,2})\s*-\s*(\d{1,2})\b", score_section)
    score_prob = re.search(r"\b\d{1,2}\s*-\s*\d{1,2}\s+(\d{1,3}(?:\.\d+)?)\s*%", score_section)
    match_id = re.search(r"/predictionsdetails/football/(\d+)/", url)
    if not match_id:
        raise ValueError("BETCLAN_EVENT_ID_MISSING")
    h, d, a = (_pct_in(win, x) for x in ("Home", "Draw", "Away"))
    if all(x is not None for x in (h, d, a)) and abs(h + d + a - 100) > 3:
        h = d = a = None
    return {
        "provider": "BETCLAN", "provider_event_id": match_id.group(1),
        "source_url": url, "home": home, "away": away,
        "competition": None, "source_kickoff_text": date.group(1) if date else None,
        "source_timezone_verified": False,
        "prediction_1x2": {"home": h, "draw": d, "away": a},
        "goals_25": {"under": _pct_in(goals, "Under"), "over": _pct_in(goals, "Over")},
        "btts": {"yes": _pct_in(btts, "Yes"), "no": _pct_in(btts, "No")},
        "correct_score": {"score": f"{score.group(1)}-{score.group(2)}" if score else None,
                          "probability": num(score_prob.group(1)) if score_prob else None},
        "tip": None, "canonical_match_id": None, "identity_status": "UNRESOLVED",
    }


def sportytrader_detail(page: str, url: str) -> dict:
    soup = BeautifulSoup(page, "html.parser")
    heading = clean(soup.h1.get_text(" ", strip=True)) if soup.h1 else ""
    teams = re.search(r"^(.+?)\s+vs\s+(.+?)\s+Prediction\b", heading, re.I)
    if not teams:
        raise ValueError("SPORTYTRADER_MATCH_HEADING_MISSING")
    home, away = clean(teams.group(1)), clean(teams.group(2))
    text = clean(soup.get_text(" ", strip=True))
    # Restrict probability extraction to the algorithm's 1X2 paragraph, never
    # team-form, H2H percentages or sportsbook implied probabilities.
    section_match = re.search(
        r"Probabilities according to our algorithm(.*?)(?:\bForm\b|\bLast Matches\b|\bStats\b)",
        text, re.I | re.S,
    )
    section = section_match.group(1) if section_match else ""
    def find(pattern: str) -> float | None:
        m = re.search(pattern, section, re.I)
        return num(m.group(1)) if m else None
    home_p = find(r"probability of\s+([\d.]+)%\s+for a win of\s+" + re.escape(home) + r"\b")
    draw_p = find(r"probability[^.]{0,120}?for a draw[^.]{0,120}?is\s+([\d.]+)%")
    away_p = find(r"([\d.]+)%\s+chance[^.]{0,70}?for a win of\s+" + re.escape(away) + r"\b")
    # Draw is sometimes written "probability ... for a draw ... is XX%".
    if draw_p is None:
        draw_p = find(r"probability[^.]{0,100}?for a draw[^.]{0,100}?\b([\d.]+)%")
    if all(x is not None for x in (home_p, draw_p, away_p)) and abs(home_p + draw_p + away_p - 100) > 3:
        home_p = draw_p = away_p = None
    tip_match = re.search(r"Our prediction for the .{5,180}? match is:\s*(.{2,110}?)(?:\.\s|Probabilities)", text, re.I)
    if not tip_match:
        tip_match = re.search(r"Prediction\s*:\s*(.{2,85}?)(?:\s+Prediction published|$)", text, re.I)
    kickoff_match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2})\b", text[:750])
    source_id = re.search(r"-(\d+)/?$", urlparse(url).path)
    if not source_id:
        raise ValueError("SPORTYTRADER_EVENT_ID_MISSING")
    return {
        "provider": "SPORTYTRADER", "provider_event_id": source_id.group(1),
        "source_url": url, "home": home, "away": away,
        "competition": heading.split(" - ", 1)[-1] if " - " in heading else None,
        "source_kickoff_text": kickoff_match.group(1) if kickoff_match else None,
        "source_timezone_verified": False,
        "prediction_1x2": {"home": home_p, "draw": draw_p, "away": away_p},
        "goals_25": {"under": None, "over": None},
        "btts": {"yes": None, "no": None},
        "correct_score": {"score": None, "probability": None},
        "tip": clean(tip_match.group(1)) if tip_match else None,
        "canonical_match_id": None, "identity_status": "UNRESOLVED",
    }


def fetch_html(session: requests.Session, url: str) -> str:
    with session.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True,
                     allow_redirects=True) as response:
        response.raise_for_status()
        if urlparse(response.url).hostname not in DOMAINS.values():
            raise ValueError("SOURCE_REDIRECT_OUTSIDE_ALLOWLIST")
        if "html" not in response.headers.get("content-type", "").lower():
            raise ValueError("SOURCE_CONTENT_TYPE_CHANGED")
        blob = bytearray()
        for chunk in response.iter_content(65536):
            blob.extend(chunk)
            if len(blob) > MAX_BYTES:
                raise ValueError("SOURCE_PAGE_TOO_LARGE")
        return blob.decode(response.encoding or "utf-8", errors="replace")


def capture(provider: str, max_details: int = 12, delay: float = 1.0) -> dict:
    if provider not in LISTINGS or not 1 <= max_details <= 40 or delay < 0.5:
        raise ValueError("INVALID_CAPTURE_BOUNDS")
    session = requests.Session()
    links, errors = [], []
    calls = 0
    for index_url in LISTINGS[provider]:
        try:
            links.extend(extract_links(provider, fetch_html(session, index_url), index_url))
            calls += 1
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"LISTING_ERROR:{type(exc).__name__}")
    links = list(dict.fromkeys(links))[:max_details]
    parser = betclan_detail if provider == "BETCLAN" else sportytrader_detail
    rows = []
    for url in links:
        time.sleep(delay)
        try:
            record = parser(fetch_html(session, url), url)
            calls += 1
            evidence = {k: record[k] for k in (
                "provider", "provider_event_id", "prediction_1x2", "goals_25", "btts",
                "correct_score", "tip",
            )}
            record["evidence_hash"] = hashlib.sha256(
                json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            record["captured_at"] = datetime.now(timezone.utc).isoformat()
            rows.append(record)
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"DETAIL_ERROR:{type(exc).__name__}")
    return {
        "provider": provider, "status": "CAPTURED_UNMATCHED" if rows else "NO_VERIFIED_CAPTURE",
        "index_links_found": len(links), "requests_ok": calls, "details": len(rows),
        "errors": errors[:20], "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("BETCLAN", "SPORTYTRADER", "BOTH"), default="BOTH")
    parser.add_argument("--max-details", type=int, default=12)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=Path("/tmp/ft-advisor-captures.json"))
    args = parser.parse_args()
    selected = list(LISTINGS) if args.provider == "BOTH" else [args.provider]
    captures = [capture(p, args.max_details, args.delay) for p in selected]
    report = {
        "schema": "fast-tracker-advisor-capture/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canonical_promotion_enabled": False, "dashboard_published": False,
        "providers": captures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({c["provider"]: {"status": c["status"], "count": c["details"],
          "errors": len(c["errors"])} for c in captures}))
    if not any(c["details"] for c in captures):
        sys.exit("No source records captured; safe failure, no publish")


if __name__ == "__main__":
    main()
