#!/usr/bin/env python3
"""Independent daily source-only capture for PrimaTips and Statarea.

No wagering, source time-zone inference, canonical identity writes or probability
imputation. Output is an evidence artifact for subsequent verified reconciliation.
At most two dated pages/provider, at most 500 records/provider/day.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

UA = "FastTrackerSourceAudit/1.0 (once daily; source-only; no credentials)"
PROVIDERS = ("PRIMATIPS", "STATAREA")
MAX_HTML = 2_000_000
MAX_ROWS_PER_PAGE = 500
_CLOCK = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_PCT = re.compile(r"^(\d{1,3})%?$")
_TIP_ID = re.compile(r"/tip/[-a-z0-9]+-(\d{4,12})/?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _pct(text):
    m = _PCT.fullmatch(str(text).strip())
    if not m:
        return None
    value = int(m.group(1))
    return value if 0 <= value <= 100 else None


def _triplet(numbers):
    if len(numbers) != 3:
        return None
    values = [_pct(value) for value in numbers]
    if any(value is None for value in values) or not 98 <= sum(values) <= 102:
        return None
    return dict(zip(("home", "draw", "away"), [round(x / 100, 4) for x in values]))


def parse_primatips(html, day):
    """Read original model percentages from .ts .t, never bookmaker odds."""
    if not _DATE.fullmatch(day):
        raise ValueError("INVALID_DATE")
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    try:
        actual = datetime.strptime(heading.get_text(" ", strip=True), "%A, %B %d, %Y").date()
    except (AttributeError, ValueError) as exc:
        raise ValueError("PRIMATIPS_DATE_HEADER_INVALID") from exc
    if actual.isoformat() != day:
        raise ValueError("PRIMATIPS_PAGE_DATE_MISMATCH")
    results, seen = [], set()
    for item in soup.select("a.game[id^='g_']")[:MAX_ROWS_PER_PAGE + 1]:
        source_id = item.get("id", "")[2:]
        url = item.get("href", "")
        m = _TIP_ID.search(url)
        if (not re.fullmatch(r"\d{4,12}", source_id) or not m
                or m.group(1) != source_id or urlparse(url).netloc != "primatips.com"
                or urlparse(url).scheme != "https"):
            continue
        names = [x.get_text(" ", strip=True) for x in item.select("span.nms span.nm")]
        clock_node = item.select_one("span.tm")
        clock = clock_node.get_text(" ", strip=True) if clock_node else ""
        probs = [x.get_text(" ", strip=True) for x in item.select("span.data span.tos span.ts span.t")]
        hda = _triplet(probs)
        if len(names) != 2 or not all(names) or names[0] == names[1] or not _CLOCK.fullmatch(clock) or not hda:
            continue
        league_node = item.select_one("span.fl img[title]")
        league = league_node["title"].strip() if league_node else ""
        if not 1 <= len(league) <= 120:
            continue
        if source_id in seen:
            continue
        seen.add(source_id)
        tip_node = item.select_one("span.to span.tip")
        tip = tip_node.get_text(" ", strip=True) if tip_node else None
        odds_nodes = [x.get_text(" ", strip=True) for x in item.select("span.data span.os span.o")]
        odds = None
        if len(odds_nodes) == 3:
            try:
                temp = [float(x) for x in odds_nodes]
                if all(1.0 < x < 1001 for x in temp):
                    odds = dict(zip(("home", "draw", "away"), temp))
            except ValueError:
                pass
        results.append({
            "source": "PRIMATIPS", "source_event_id": source_id,
            "event_id_basis": "PROVIDER_LINKED_EVENT_ID", "source_url": url,
            "source_home": names[0], "source_away": names[1],
            "source_competition": league, "source_date": day,
            "source_wall_time": clock, "source_kickoff": None,
            "kickoff_timezone_verified": False,
            "hda": hda, "tip": tip if tip in ("1","X","2","1X","X2","12") else None,
            "source_average_1x2_odds": odds, "identity_status": "UNRESOLVED",
        })
    if len(results) > MAX_ROWS_PER_PAGE:
        raise ValueError("PRIMATIPS_PAGE_ROW_CAP")
    return results


def parse_statarea(html, day):
    """Read only the basic-HTML table's explicit prediction percentage row.

    Statarea does not expose a stable fixture ID in this surface: the hash
    is an observation key, NOT proof of Flashscore identity.
    """
    if not _DATE.fullmatch(day):
        raise ValueError("INVALID_DATE")
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")
    if not any(("All predictions for" in row.get_text(" ", strip=True) and day in row.get_text(" ", strip=True))
               for row in rows):
        raise ValueError("STATAREA_PAGE_DATE_MISMATCH")
    result, seen = [], set()
    league = clock = tip = None
    names = []
    page_url = f"https://www.statarea.com/olddevices/prediction/{day}/"
    for tr in rows:
        cols = tr.find_all("td", recursive=False)
        vals = [td.get_text(" ", strip=True) for td in cols]
        if len(cols) == 2 and cols[0].find("img") and cols[1].get("colspan") == "10":
            league = vals[1][:120]
            clock = tip = None
            names = []
            continue
        if len(cols) == 1 and vals[0].startswith("time:"):
            clock = vals[0].split(":", 1)[1].strip()
            tip = None
            names = []
            continue
        if len(cols) == 2 and vals[0].startswith("prediction:"):
            tip = vals[0].split(":", 1)[1].strip()
            continue
        if (len(cols) == 2 and cols[0].get("colspan") == "10"
                and cols[1].get_text(" ", strip=True) in ("-", "")
                and not vals[0].startswith(("prediction:", "time:"))
                and clock and league):
            if len(names) < 2:
                names.append(vals[0])
            continue
        if len(cols) != 11 or len(names) != 2 or not league or not clock:
            continue
        if not _CLOCK.fullmatch(clock):
            names = []
            continue
        percents = [_pct(v) for v in vals]
        # Headers ("1", "X", "2") are not percentages: keep the team pair
        # until the subsequent actual percentage row is read.
        if any(v is None for v in percents[:3]):
            continue
        hda = _triplet(vals[:3])
        if not hda or not names[0] or not names[1] or names[0] == names[1]:
            names = []
            continue
        source_id = hashlib.sha256("|".join((day,league,clock,*names)).encode()).hexdigest()[:24]
        if source_id not in seen:
            seen.add(source_id)
            result.append({
                "source": "STATAREA", "source_event_id": source_id,
                "event_id_basis": "OBSERVATION_HASH_NOT_PROVIDER_ID",
                "source_url": page_url, "source_home": names[0], "source_away": names[1],
                "source_competition": league, "source_date": day,
                "source_wall_time": clock, "source_kickoff": None,
                "kickoff_timezone_verified": False, "hda": hda,
                "over25": round(percents[7] / 100, 4) if percents[7] is not None else None,
                "btts_yes": round(percents[9] / 100, 4) if percents[9] is not None else None,
                "tip": tip if tip in ("1","X","2","1X","X2","12") else None,
                "identity_status": "UNRESOLVED",
            })
        names = []
        if len(result) > MAX_ROWS_PER_PAGE:
            raise ValueError("STATAREA_PAGE_ROW_CAP")
    return result


def fetch(session, url):
    host = urlparse(url).netloc
    if host not in ("primatips.com", "www.statarea.com") or urlparse(url).scheme != "https":
        raise ValueError("SOURCE_HOST_NOT_ALLOWED")
    response = session.get(url, headers={"User-Agent": UA}, timeout=(5, 15))
    response.raise_for_status()
    if urlparse(response.url).netloc != host:
        raise ValueError("SOURCE_REDIRECTED")
    if len(response.content) > MAX_HTML:
        raise ValueError("SOURCE_TOO_LARGE")
    return response.text


def collect(start=None, session=None):
    start = start or datetime.now(timezone.utc).date()
    session = session or requests.Session()
    output = {
        "contract": "ADVISER_EXTRA_EVIDENCE_ONLY_V1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "publication_enabled": False, "providers": {}, "records": [],
    }
    for source in PROVIDERS:
        stats = {"attempted_dates": 2, "successful_dates": 0, "parsed": 0, "failures": []}
        for shift in (0, 1):
            day = (start + timedelta(days=shift)).isoformat()
            url = (f"https://primatips.com/tips/{day}" if source == "PRIMATIPS"
                   else f"https://www.statarea.com/olddevices/prediction/{day}/")
            try:
                html = fetch(session, url)
                batch = parse_primatips(html, day) if source == "PRIMATIPS" else parse_statarea(html, day)
                if not batch:
                    info = ""
                    if source == "PRIMATIPS":
                        soup = BeautifulSoup(html, "html.parser")
                        first = soup.select_one("a.game")
                        info = (" n_links=" + str(len(soup.select("a.game")))
                                + " n_team_names=" + str(len(soup.select("a.game span.nms span.nm")))
                                + " n_percentages=" + str(len(soup.select("a.game span.ts span.t")))
                                + " first_href=" + str((first.get("href") if first else "") or "")[:100])
                    raise ValueError("EMPTY_SOURCE_PARSE" + info)
                output["records"].extend(batch)
                stats["parsed"] += len(batch)
                stats["successful_dates"] += 1
            except (requests.RequestException, ValueError) as exc:
                stats["failures"].append({"date": day, "error": type(exc).__name__, "reason": str(exc)[:250]})
        output["providers"][source] = stats
    return output


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    report = collect()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    print("ADVISER_EXTRA_EVIDENCE", json.dumps({
        "providers": report["providers"], "records": len(report["records"]),
        "production_published": False, "kickoff_timezone_verified": 0,
    }, ensure_ascii=False))
    return 0 if any(v["successful_dates"] >= 1 for v in report["providers"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
