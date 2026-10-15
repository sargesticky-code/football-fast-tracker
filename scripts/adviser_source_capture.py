#!/usr/bin/env python3
"""Bounded, evidence-only captures of BetClan and SportyTrader soccer tips.

This deliberately does NOT match provider names directly to Flashscore IDs.
The canonical reconciliation job must verify date, competition, both teams and
non-overlapping identity before a tip can become a dashboard adviser.
"""
import argparse
import json
import hashlib
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SOURCES = {
    "BETCLAN": (
        "https://www.betclan.com/todays-football-predictions/",
        "https://www.betclan.com/tomorrows-football-predictions/",
    ),
    "SPORTYTRADER": (
        "https://www.sportytrader.com/en/betting-tips/football/",
        "https://www.sportytrader.com/en/betting-tips/football/tomorrow/",
    ),
}
HOSTS = {"BETCLAN": "www.betclan.com", "SPORTYTRADER": "www.sportytrader.com"}
UA = "FastTracker-SourceAudit/1.0 (daily, bounded, no personal data)"
PERCENT = r"(\d{1,3}(?:\.\d+)?)\s*%"


def section(text, start, end):
    a = re.search(start, text, re.I)
    if not a:
        return ""
    s = text[a.end():]
    b = re.search(end, s, re.I)
    return s[:b.start()] if b else s[:1500]


def percentage(raw):
    if raw is None:
        return None
    n = float(raw)
    return round(n / 100, 6) if 0 <= n <= 100 else None


def valid_triplet(p):
    if not isinstance(p, dict) or any(type(p.get(x)) not in (int, float) or not math.isfinite(p[x]) or not 0 <= p[x] <= 1 for x in ("home", "draw", "away")):
        return None
    return p if abs(sum(p[x] for x in ("home", "draw", "away")) - 1) <= 0.025 else None


def parse_betclan(html, url):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None
    match = re.search(r"(.+?)\s+vs?\s+(.+?)\s+(?:Prediction|H2H)", h1.get_text(" ", strip=True), re.I)
    if not match:
        return None
    text = soup.get_text(" ", strip=True)
    dt = re.search(r"\bDate\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", text)
    if not dt:
        return None
    winner = section(text, r"\bWinner\b", r"\bTotal Goals\s*2\.5\b")
    probs = {
        key: percentage(re.search(r"\b" + key + r"\s*" + PERCENT, winner, re.I).group(1))
        if re.search(r"\b" + key + r"\s*" + PERCENT, winner, re.I) else None
        for key in ("Home", "Draw", "Away")
    }
    goal = section(text, r"\bTotal Goals\s*2\.5\b", r"\bBoth Teams to Score\b")
    btts = section(text, r"\bBoth Teams to Score\b", r"\bCorrect Score\b")
    # Navigation contains 'Correct Score Calculator' before the fixture date.
    # Only the actual market heading and its immediate value are evidence.
    heading = soup.find("h4", string=re.compile(r"^\s*Correct Score\s*$", re.I))
    value = heading.find_next_sibling() if heading else None
    score = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})(?:\s+\d{1,3}%\s+Others\s+\d{1,3}%)?",
                         value.get_text(" ", strip=True) if value and value.name in ("h5", "p") else "")
    event = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        for item in obj if isinstance(obj, list) else [obj]:
            if (isinstance(item, dict) and item.get("@type") == "SportsEvent"
                and item.get("url") == url
                and item.get("homeTeam", {}).get("name") == match.group(1).strip()
                and item.get("awayTeam", {}).get("name") == match.group(2).strip()):
                event = item
    kickoff = None
    if event and re.search(r"(?:Z|[+-]\d{2}:\d{2})$", str(event.get("startDate", ""))):
        try:
            at = datetime.fromisoformat(event["startDate"].replace("Z", "+00:00"))
            if at.strftime("%Y-%m-%d %H:%M") == f"{dt.group(1)} {dt.group(2)}":
                kickoff = at.isoformat()
        except ValueError:
            pass
    return {
        "source": "BETCLAN", "source_url": url,
        "source_event_id": re.search(r"/football/(\d+)/", url).group(1),
        "home": match.group(1).strip(), "away": match.group(2).strip(),
        "source_date": dt.group(1), "source_wall_time": dt.group(2),
        "kickoff_timezone_verified": kickoff is not None,
        "source_kickoff": kickoff,
        "source_timezone": kickoff[-6:] if kickoff else None,
        "source_competition": event.get("organizer", {}).get("name") if event else None,
        "source_event_status": event.get("eventStatus") if event else None,
        "raw_content_hash": hashlib.sha256(html.encode()).hexdigest(),
        "parser_version": "betclan-v2-structured-event",
        "hda": valid_triplet({k.lower(): v for k, v in probs.items()}),
        "over25": percentage(re.search(r"\bOver\s*" + PERCENT, goal, re.I).group(1))
        if re.search(r"\bOver\s*" + PERCENT, goal, re.I) else None,
        "btts_yes": percentage(re.search(r"\bYes\s*" + PERCENT, btts, re.I).group(1))
        if re.search(r"\bYes\s*" + PERCENT, btts, re.I) else None,
        "predicted_score": f"{score.group(1)}-{score.group(2)}" if score else None,
        "canonical_event_id": None, "identity": "UNRESOLVED",
    }


def parse_sportytrader(html, url):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None
    title = h1.get_text(" ", strip=True)
    pair = re.search(r"(.+?)\s+vs?\s+(.+?)\s+Prediction\b", title, re.I)
    if not pair:
        return None
    text = soup.get_text(" ", strip=True)
    dt = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})\b", text)
    if not dt:
        return None
    pick = section(text, r"\bPrediction\s*:", r"(?:Prediction published|Bookmaker|New customers)")
    # Remove bookmaker decimal quote without corrupting a tip such as "Under 2.5 goals".
    pick = re.split(r"\s+New customers\b", pick, flags=re.I, maxsplit=1)[0].strip()
    pick = re.sub(r"\s+[1-9]\d{0,2}\.\d{2}$", "", pick).strip()[:90]
    # Parse genuine SportyTrader algorithm probabilities, not bookmaker odds.
    algorithm = section(text, r"Probabilities according to our algorithm", r"Prediction and Best Odds")
    h = re.search(r"probability of\s*" + PERCENT + r"\s+for a win of", algorithm, re.I)
    d = re.search(r"for a draw\b.{0,160}?\bis\s*" + PERCENT, algorithm, re.I)
    a = re.search(r"(?:model gives|model estimates)\s+(?:a\s+)?" + PERCENT + r"\s+chance.{0,100}?for a win of", algorithm, re.I)
    hda = valid_triplet({
        "home": percentage(h.group(1)) if h else None,
        "draw": percentage(d.group(1)) if d else None,
        "away": percentage(a.group(1)) if a else None,
    })
    return {
        "source": "SPORTYTRADER", "source_url": url,
        "source_event_id": re.search(r"-(\d+)/?$", url).group(1),
        "home": pair.group(1).strip(), "away": pair.group(2).strip(),
        "source_date": f"{dt.group(3)}-{dt.group(2)}-{dt.group(1)}",
        "source_wall_time": dt.group(4), "kickoff_timezone_verified": False,
        # A written tip is not a probability triplet; never invent 1X2 from odds.
        "tip": pick or None, "hda": hda, "canonical_event_id": None,
        "identity": "UNRESOLVED",
    }


def candidate_urls(html, source):
    soup = BeautifulSoup(html, "html.parser")
    found = set()
    for anchor in soup.find_all("a", href=True):
        url = urljoin(SOURCES[source][0], anchor["href"])
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != HOSTS[source]:
            continue
        if source == "BETCLAN" and not re.search(r"/predictionsdetails/football/\d+/", parsed.path):
            continue
        if source == "SPORTYTRADER" and not re.fullmatch(r"/en/betting-tips/[^/]+-\d+/", parsed.path):
            continue
        found.add(parsed._replace(query="", fragment="").geturl())
    return sorted(found)


def fetch(session, url):
    response = session.get(url, timeout=(5, 12), headers={"User-Agent": UA})
    response.raise_for_status()
    if urlparse(response.url).hostname != urlparse(url).hostname:
        raise RuntimeError("provider_redirected_to_another_host")
    if len(response.content) > 2_000_000:
        raise RuntimeError("page_too_large")
    return response.text


def collect(limit=100, pause=0.4, session=None, source=None, evidence_dir=None):
    if source is not None and source not in SOURCES:
        raise ValueError("unknown_source")
    if not 1 <= limit <= 120:
        raise ValueError("invalid_source_limit")
    selected_source = source
    session = session or requests.Session()
    output = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "contract": "source_observations_only_v1", "providers": {}, "records": []}
    for source, listings in SOURCES.items():
        if selected_source is not None and source != selected_source:
            continue
        diag = {"listings_ok": 0, "candidate_urls": 0, "parsed": 0, "failed": 0,
                "status": "UNAVAILABLE"}
        urls = set()
        for url in listings:
            try:
                urls.update(candidate_urls(fetch(session, url), source))
                diag["listings_ok"] += 1
            except (requests.RequestException, RuntimeError) as exc:
                diag["last_error"] = type(exc).__name__
            time.sleep(pause)
        diag["candidate_urls"] = len(urls)
        for url in sorted(urls)[:limit]:
            try:
                html = fetch(session, url)
                evidence_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
                if evidence_dir is not None:
                    evidence_path = Path(evidence_dir) / source.lower() / (evidence_hash + ".html")
                    evidence_path.parent.mkdir(parents=True, exist_ok=True)
                    evidence_path.write_text(html, encoding="utf-8")
                parsed = (parse_betclan(html, url) if source == "BETCLAN"
                          else parse_sportytrader(html, url))
                if parsed is None:
                    raise ValueError("invalid_source_detail_structure")
                parsed["captured_at"] = output["generated_at"]
                parsed["raw_content_hash"] = evidence_hash
                output["records"].append(parsed)
                diag["parsed"] += 1
            except (requests.RequestException, RuntimeError, ValueError, AttributeError) as exc:
                diag["failed"] += 1
                diag["last_error"] = type(exc).__name__
            time.sleep(pause)
        diag["status"] = ("CAPTURED_UNMATCHED" if diag["parsed"] else
                          "PARSE_FAILED" if diag["candidate_urls"] else "SOURCE_UNAVAILABLE")
        output["providers"][source] = diag
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--source", choices=tuple(SOURCES))
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit <= 120:
        parser.error("limit must be 1..120 per source")
    report = collect(limit=args.limit, source=args.source, evidence_dir=args.evidence_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"providers": report["providers"], "total": len(report["records"]) }))
    if not report["records"]:
        raise SystemExit("capture failed: no source-backed adviser records; no ingestion")
