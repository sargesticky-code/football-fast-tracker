#!/usr/bin/env python3
"""Bounded, HKJC-independent Forebet source capture (DRY RUN ONLY).

Reuses the existing Forebet parser and the public canonical fixture summary.
No background schedule, publication, secrets, paid proxy, database writes, or
alias registry copies. An ambiguous or timezone-unverified match is discarded.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from scrape_forebet import parse_forebet_rows

API = "https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/app-phase1-feed?view=summary&hours=48"
SOURCE_URL = "https://www.forebet.com/en/football-predictions/predictions-1x2/{}"
OUT = Path("/tmp/ft_forebet_canonical_source_probe.json")
TIMEOUT = 15
MAX_DATES = 3
MAX_FIXTURES = 350
MAX_HTML_BYTES = 2_000_000
MAX_DRIFT_SECONDS = 600
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FastTrackerSourceProbe/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Cache-Control": "no-cache",
}

def aware_time(value):
    try:
        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip()
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None

def exact_name(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch for ch in text if ch.isalnum())

def model_fields(row):
    try:
        h, d, a = (float(row[k]) for k in ("prob_home", "prob_draw", "prob_away"))
        avg = float(row["avg_goals"])
        pick = str(row.get("prediction_1x2") or "").strip().upper()
        score = str(row.get("predicted_score") or "").strip()
        if any(not (0 <= n <= 100) for n in (h, d, a)):
            return None
        if not (98 <= h + d + a <= 102 and 0 < avg <= 12):
            return None
        if pick not in {"1", "X", "2"} or not re.fullmatch(r"\d{1,2}\s*-\s*\d{1,2}", score):
            return None
        if not row.get("forebet_detail_url"):
            return None
        url = str(row["forebet_detail_url"])
        host = urlparse(url)
        if host.scheme != "https" or host.hostname not in {"forebet.com", "www.forebet.com"}:
            return None
        return {"home": h, "draw": d, "away": a, "pick": pick,
                "score": re.sub(r"\s+", " ", score), "avg_goals": avg}
    except (KeyError, TypeError, ValueError):
        return None

def canonical_targets(matches, now):
    targets = []
    if not isinstance(matches, list) or len(matches) > MAX_FIXTURES:
        raise ValueError("canonical fixture feed unavailable or above bounded limit")
    for m in matches:
        if not isinstance(m, dict):
            continue
        match_id = str(m.get("id") or "")
        kickoff = aware_time(m.get("kickoff"))
        if not re.fullmatch(r"[A-Za-z0-9:_-]{2,80}", match_id) or not kickoff:
            continue
        if not now - timedelta(hours=2) <= kickoff <= now + timedelta(hours=48):
            continue
        home, away = str(m.get("home") or "").strip(), str(m.get("away") or "").strip()
        if not home or not away or exact_name(home) == exact_name(away):
            continue
        targets.append({"match_id": match_id, "kickoff": kickoff,
                        "home": home, "away": away,
                        "league": str(m.get("league") or "")})
    return targets

def build_verified_rows(targets, rows, captured_at):
    """Exact, unique team pair AND provider ISO kickoff. Never fuzzy-match."""
    candidates = {}
    for target in targets:
        key = (exact_name(target["home"]), exact_name(target["away"]))
        candidates.setdefault(key, []).append(target)
    by_id = {}
    ambiguous = set()
    for row in rows:
        when = aware_time(row.get("source_kickoff_iso"))
        fields = model_fields(row)
        if not when or not fields:
            continue
        key = (exact_name(row.get("home_team")), exact_name(row.get("away_team")))
        matching = [t for t in candidates.get(key, [])
                    if abs((when - t["kickoff"]).total_seconds()) <= MAX_DRIFT_SECONDS]
        if len(matching) != 1:
            continue
        target = matching[0]
        match_id = target["match_id"]
        if match_id in by_id:
            ambiguous.add(match_id)
            continue
        by_id[match_id] = {
            "match_id": match_id, "captured_at": captured_at.isoformat(),
            "kickoff": target["kickoff"].isoformat(),
            "canonical_home": target["home"], "canonical_away": target["away"],
            "source_home": str(row["home_team"]).strip(),
            "source_away": str(row["away_team"]).strip(),
            "home": fields["home"], "draw": fields["draw"], "away": fields["away"],
            "pick": fields["pick"], "score": fields["score"],
            "avg_goals": fields["avg_goals"], "match_score": 0.995,
            "match_date": str(row.get("match_date") or ""),
            "kickoff_text": str(row.get("kickoff_text") or ""),
            "league": str(row.get("league_short") or ""),
            "source_event_url": row["forebet_detail_url"],
            "source_event_time": row["source_kickoff_iso"],
            "identity_method": "EXACT_TEAMS_AND_PROVIDER_TIME",
        }
    return [v for k, v in sorted(by_id.items()) if k not in ambiguous]

def get_json(session, url):
    response = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    if len(response.content) > MAX_HTML_BYTES:
        raise ValueError("oversize canonical feed")
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("matches"), list):
        raise ValueError("canonical feed has no matches array")
    # A degraded direct collector snapshot still contains fixtures but does not
    # prove canonical identity. Never publish from it.
    if not str(data.get("source", "")).startswith(("flashscore-single-rpc-canonical", "supabase-canonical-live", "flashscore-direct")):
        raise ValueError("unsupported fixture source provenance")
    return data["matches"]

def get_source_html(session, date):
    response = session.get(SOURCE_URL.format(date), headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    if len(response.content) > MAX_HTML_BYTES or "rcnt" not in response.text:
        raise ValueError(f"Forebet page unavailable or does not contain match rows: {date}")
    return response.text

def capture(session=None, now=None):
    session = session or requests.Session()
    now = now or datetime.now(timezone.utc)
    matches = get_json(session, API)
    targets = canonical_targets(matches, now)
    if not targets:
        raise ValueError("no eligible canonical fixtures")
    # Forebet pages are date-scoped. Never hit more than three dates or fallback
    # to historical/source-blind broad crawling.
    dates = sorted({t["kickoff"].astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d") for t in targets})
    if len(dates) > MAX_DATES:
        raise ValueError("more source dates than safety ceiling")
    source_rows = []
    for date in dates:
        source_rows.extend(parse_forebet_rows(get_source_html(session, date), date))
    return {
        "status": "DRY_RUN_NOT_PUBLISHED",
        "fixture_source": "canonical-phase1-summary",
        "provider": "FOREBET",
        "fetched_at": now.isoformat(),
        "target_count": len(targets),
        "date_calls": len(dates),
        "source_rows": len(source_rows),
        "rows": build_verified_rows(targets, source_rows, now),
    }

def main():
    try:
        result = capture()
    except (requests.RequestException, ValueError) as exc:
        print(f"FOREBET_SOURCE_PROBE_UNAVAILABLE {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FOREBET_SOURCE_PROBE " + json.dumps({
        "target_count": result["target_count"], "date_calls": result["date_calls"],
        "source_rows": result["source_rows"], "verified_rows": len(result["rows"]),
        "published": False,
    }, sort_keys=True))
    # Zero verified rows is a truthful blocked result, not a publishable batch.
    return 0 if result["rows"] else 3

if __name__ == "__main__":
    raise SystemExit(main())
