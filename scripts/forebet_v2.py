#!/usr/bin/env python3
"""Forebet V2: one source page, DB-verified Flashscore fixture identities only.

No public dashboard dependency, HKJC feed, fuzzy matcher, per-row DB writes,
HTML archive, retries, or additional scraping. The previously corroborated
Forebet page-clock offset is UTC+0 (2026-10-10 run 38061748513, 20 matches).
Any later timezone change fails match checks rather than silently remapping.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from forebet_browser_source import load_canonical_candidates
from forebet_canonical_source_probe import canonical_targets, exact_name, model_fields, aware_time
from forebet_verified_aliases import source_forms, verified_source_name
from capture_forebet_canonical_light import displayed_wall_clock, league_ok, LEAGUE_PREFIX

API = "https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/forebet-canonical-publish"
HKT = timezone(timedelta(hours=8))
OUT = Path("/tmp/ft-forebet-verified-only.json")
SUMMARY = Path("/tmp/ft-forebet-verified-summary.json")
MAX_TARGETS = 350
# Fixed from 20 independent verified fixtures. If the provider changes its
# display timezone, exact UTC kickoff comparisons reject affected rows.
CALIBRATED_DISPLAY_UTC_OFFSET_MINUTES = 0


def canonical_from_oidc(token: str, now: datetime, session=None) -> list[dict]:
    if not token or len(token) < 50:
        raise ValueError("GITHUB_OIDC_MISSING")
    session = session or requests.Session()
    resp = session.get(API, headers={"Authorization": f"Bearer {token}",
             "Accept": "application/json"}, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("source") != "flashscore-verified-canonical-fixtures-v2":
        raise ValueError("NOT_FLASHScore_VERIFIED_CANONICAL_FEED")
    at = aware_time(payload.get("generatedAt"))
    if at is None or not -60 <= (now-at).total_seconds() <= 1200:
        raise ValueError("STALE_CANONICAL_FEED")
    fixtures = payload.get("matches")
    if not isinstance(fixtures, list) or not 8 <= len(fixtures) <= MAX_TARGETS:
        raise ValueError("INVALID_VERIFIED_CANONICAL_FIXTURES")
    for m in fixtures:
        if (not isinstance(m, dict)
            or not re.fullmatch(r"FS:[A-Za-z0-9_-]{5,32}", str(m.get("id") or ""))
            or (m.get("sourceContext") or {}).get("identityStatus") != "EXACT_CANONICAL_PROVIDER_FIXTURE"
            or (m.get("sourceContext") or {}).get("provider") != "FLASHSCORE"
            or not aware_time(m.get("kickoff"))):
            raise ValueError("UNVERIFIED_CANONICAL_ROW")
    return canonical_targets(fixtures, now)


def verified_rows(source_rows: list[dict], targets: list[dict], now: datetime):
    """Unique home+away, verified competition, exact UTC kickoff.

    Does NOT require unrelated fixtures to exist just to verify one match.
    Unknown and duplicate rows remain unpublished.
    """
    catalog = {}
    for t in targets:
        if not re.fullmatch(r"FS:[A-Za-z0-9_-]{5,32}", str(t.get("match_id", ""))):
            continue
        for home in source_forms(t["home"]):
            for away in source_forms(t["away"]):
                catalog.setdefault((home, away), []).append(t)
    emitted, rejected, links, blocked_ids = {}, Counter(), set(), set()
    for row in source_rows:
        fields = model_fields(row)
        wall = displayed_wall_clock(row)
        if not fields or wall is None:
            rejected["SOURCE_FIELDS_OR_CLOCK"] += 1
            continue
        home = exact_name(row.get("home_team"))
        away = exact_name(row.get("away_team"))
        pair = catalog.get((home, away), [])
        if not pair:
            rejected["SOURCE_TEAM_PAIR_NOT_IN_VERIFIED_FIXTURES"] += 1
            continue
        known_league = str(row.get("league_short") or "") in LEAGUE_PREFIX
        possibles = []
        for t in pair:
            if not now < t["kickoff"] <= now + timedelta(hours=60):
                continue
            exactly_named = home == exact_name(t["home"]) and away == exact_name(t["away"])
            if not (verified_source_name(row.get("home_team"), t["home"]) and
                    verified_source_name(row.get("away_team"), t["away"])):
                continue
            # Known source codes must corroborate competition. For *unknown*
            # code, permit only TWO exact team names + exact UTC kickoff.
            # Never promote a fuzzy alias under an unverified league code.
            if known_league and not league_ok(row.get("league_short"), t.get("league")):
                continue
            if not known_league and not exactly_named:
                continue
            expected = t["kickoff"].astimezone(timezone.utc).replace(tzinfo=None)
            if abs((wall-expected).total_seconds()) > 60:
                rejected["CLOCK_OFFSET_CHANGED_OR_WRONG_FIXTURE"] += 1
                continue
            possibles.append(t)
        if len(possibles) != 1:
            rejected["NO_UNIQUE_VERIFIED_TEAM_TIME_AND_LEAGUE"] += 1
            continue
        t = possibles[0]
        mid, link = t["match_id"], row["forebet_detail_url"]
        if mid in emitted or mid in blocked_ids or link in links:
            emitted.pop(mid, None)
            blocked_ids.add(mid)
            rejected["DUPLICATE_SOURCE_OR_CANONICAL_EVENT"] += 1
            continue
        links.add(link)
        exact = home == exact_name(t["home"]) and away == exact_name(t["away"])
        emitted[mid] = {
            "match_id":mid,"captured_at":now.isoformat(),
            "kickoff":t["kickoff"].isoformat(),
            "canonical_home":t["home"],"canonical_away":t["away"],
            "source_home":row["home_team"],"source_away":row["away_team"],
            "home":fields["home"],"draw":fields["draw"],"away":fields["away"],
            "pick":fields["pick"],"score":fields["score"],"avg_goals":fields["avg_goals"],
            "match_score":0.995 if exact else 0.985,
            "match_date":str(row.get("match_date") or ""),
            "kickoff_text":str(row.get("kickoff_text") or ""),
            "league":str(row.get("league_short") or ""),
            "source_league":str(row.get("league_short") or ""),
            "source_event_url":link,
            "league_verification":"VERIFIED_SOURCE_CODE" if known_league else "EXACT_NAMES_AND_UTC_TIME_ONLY",
            "source_event_time":t["kickoff"].isoformat(),
            "source_event_time_basis":"CALIBRATED_PROVIDER_UTC_AND_EXACT_CANONICAL_KICKOFF",
            "source_display_offset_minutes":CALIBRATED_DISPLAY_UTC_OFFSET_MINUTES,
            "identity_method":"EXACT_TEAMS_LEAGUE_AND_CALIBRATED_UTC_TIME" if exact
                else "VERIFIED_ALIAS_LEAGUE_AND_CALIBRATED_UTC_TIME"
        }
    return [emitted[k] for k in sorted(emitted)], dict(rejected)


def run(now=None, fixture_token=None, helper=None):
    now = now or datetime.now(timezone.utc)
    fixture_token = fixture_token or os.getenv("FOREBET_FIXTURES_OIDC", "")
    targets = canonical_from_oidc(fixture_token, now)
    if len(targets) < 8:
        raise ValueError("TOO_FEW_VERIFIED_FS_FIXTURES")
    date = (now.astimezone(HKT) + timedelta(days=1)).strftime("%Y-%m-%d")
    source_url = "https://www.forebet.com/en/football-predictions/predictions-1x2/" + date
    candidates, details = load_canonical_candidates(
        source_url, date, targets,
        helper=helper or os.getenv("LOCAL_BROWSER_HELPER", "http://127.0.0.1:8191/v1"))
    rows, rejected = verified_rows(candidates, targets, now)
    summary = {
        "provider":"FOREBET","version":2,"date":date,
        "captured_at":now.isoformat(),"canonical_source":"VERIFIED_FLASHSCORE_DB",
        "canonical_targets":len(targets),
        "source_dom_rows":details.get("expanded"),
        "known_team_pair_rows":details.get("matched"),
        "source_rows_parsed":len(candidates),
        "strict_verified_models":len(rows),
        "calibrated_utc_offset_minutes":CALIBRATED_DISPLAY_UTC_OFFSET_MINUTES,
        "rejections":rejected,"published":False
    }
    OUT.write_text(json.dumps({"source":"FOREBET","rows":rows},
                              ensure_ascii=False), encoding="utf-8")
    SUMMARY.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("FOREBET_V2_PROOF "+json.dumps(summary,ensure_ascii=False),flush=True)
    return summary


if __name__ == "__main__":
    try:
        report = run()
        sys.exit(0 if report["strict_verified_models"] else 3)
    except (ValueError, requests.RequestException) as exc:
        print("FOREBET_V2_FAILED "+type(exc).__name__+" "+str(exc)[:200],file=sys.stderr)
        sys.exit(2)
