#!/usr/bin/env python3
"""Forebet V2: bounded multi-date capture and DB-verified Flashscore identity.

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
from playwright.sync_api import Error as BrowserError

from forebet_browser_source import load_canonical_candidates
from forebet_market_capture_v2 import parse_ou25, parse_corners95, enrich_verified_rows, MAX_MARKET_PAGES
from forebet_intersection_audit import source_intersection_audit
from forebet_provisional import tentative_rows
from forebet_canonical_source_probe import canonical_targets, exact_name, model_fields, aware_time
from forebet_verified_aliases import source_forms, verified_source_name, verified_shared_source_name
from capture_forebet_canonical_light import displayed_wall_clock, league_ok, LEAGUE_PREFIX

API = "https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/forebet-canonical-publish"
HKT = timezone(timedelta(hours=8))
OUT = Path("/tmp/ft-forebet-verified-only.json")
SUMMARY = Path("/tmp/ft-forebet-verified-summary.json")
PROVISIONAL_OUT = Path("/tmp/ft-forebet-provisional-only.json")
MAX_TARGETS = 600
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
                # A missing source league code may be bridged only when BOTH
                # source and target team identities are independently verified
                # by both providers; exact UTC kickoff and uniqueness remain
                # mandatory. Never permit one-sided or legacy-only guesses.
                if not (
                    verified_shared_source_name(row["home_team"],t["home"]) is True
                    and verified_shared_source_name(row["away_team"],t["away"]) is True
                ):
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
        bridge_proven = (
            (home != exact_name(t["home"]) and
             verified_shared_source_name(row["home_team"], t["home"]) is True)
            or (away != exact_name(t["away"]) and
                verified_shared_source_name(row["away_team"], t["away"]) is True)
        )
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
            "league_verification":"VERIFIED_SOURCE_CODE" if known_league
                else ("EXACT_NAMES_AND_UTC_TIME_ONLY" if exact
                      else "TWO_SHARED_PROVIDER_TEAM_KEYS_AND_UNIQUE_UTC_FIXTURE"),
            "source_event_time":wall.replace(tzinfo=timezone.utc).isoformat(),
            "source_event_time_basis":"CALIBRATED_PROVIDER_UTC_AND_EXACT_CANONICAL_KICKOFF",
            "source_display_offset_minutes":CALIBRATED_DISPLAY_UTC_OFFSET_MINUTES,
            "identity_method":"EXACT_TEAMS_LEAGUE_AND_CALIBRATED_UTC_TIME" if exact
                else ("TWO_SHARED_PROVIDER_KEYS_UNKNOWN_LEAGUE_EXACT_UTC_TIME"
                      if not known_league else
                      ("VERIFIED_SHARED_PROVIDER_BRIDGE_AND_EXACT_TIME" if bridge_proven
                       else "VERIFIED_ALIAS_LEAGUE_AND_CALIBRATED_UTC_TIME"))
        }
    return [emitted[k] for k in sorted(emitted)], dict(rejected)


MAX_SOURCE_DATES = 3
MAX_PUBLICATION_ROWS = 300


def source_dates(targets, now):
    """Source's calibrated display clock is UTC, not HKT.
    Cover the UTC calendar days of upcoming verified fixtures, max 3 dates.
    """
    dates = sorted({
        t["kickoff"].astimezone(timezone.utc).date().isoformat()
        for t in targets
        if now < t["kickoff"] <= now + timedelta(hours=48)
    })
    if not 1 <= len(dates) <= MAX_SOURCE_DATES:
        raise ValueError("SOURCE_DATE_WINDOW_OUT_OF_BOUNDS")
    return dates


def dedupe_repeated_source_rows(rows):
    """Exact duplicates from overlapping pages are one source observation.
    Conflicting versions remain duplicated and are fail-closed by verified_rows.
    """
    unique = []
    seen = set()
    for row in rows:
        signature = (row.get("forebet_detail_url"),
                     row.get("home_team"), row.get("away_team"),
                     row.get("kickoff_text"), row.get("prob_home"),
                     row.get("prob_draw"), row.get("prob_away"),
                     row.get("predicted_score"), row.get("avg_goals"))
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(row)
    return unique



def source_overlap_diagnostics(source_rows, targets, now):
    """Account for source/global mismatch without guessing missing aliases.

    Same kickoff alone is never evidence of matching identity; these are only
    aggregate QA counters to prioritize verified alias work in later reviews.
    """
    counts = Counter()
    end = now + timedelta(hours=48)
    for row in source_rows:
        wall = displayed_wall_clock(row)
        if not model_fields(row) or wall is None:
            counts["invalid_model_or_display_clock"] += 1
            continue
        when = wall.replace(tzinfo=timezone.utc)
        if not now < when <= end:
            counts["outside_48h_verified_fixture_window"] += 1
            continue
        possibilities = [t for t in targets if abs((t["kickoff"]-when).total_seconds()) <= 60]
        if not possibilities:
            counts["no_flashscore_fixture_with_same_kickoff"] += 1
            continue
        home = exact_name(row.get("home_team"))
        away = exact_name(row.get("away_team"))
        if any(home == exact_name(t["home"]) and away == exact_name(t["away"]) for t in possibilities):
            counts["exact_team_pair_and_kickoff"] += 1
        elif any(home == exact_name(t["home"]) or away == exact_name(t["away"]) for t in possibilities):
            counts["one_exact_team_at_same_kickoff_needs_review"] += 1
        else:
            counts["no_exact_team_at_same_kickoff"] += 1
    return dict(counts)



def candidate_pair_diagnostics(source_rows,targets,now):
    """Read-only reason accounting for known pairs not admitted by matcher."""
    catalog={}
    for t in targets:
        for h in source_forms(t["home"]):
            for a in source_forms(t["away"]):
                catalog.setdefault((h,a),[]).append(t)
    reasons=Counter()
    for row in source_rows:
        if not model_fields(row):
            continue
        wall=displayed_wall_clock(row)
        if wall is None:
            continue
        home=exact_name(row.get("home_team"))
        away=exact_name(row.get("away_team"))
        pairs=catalog.get((home,away),[])
        if not pairs:
            continue
        candidates=[]
        for t in pairs:
            reason=""
            if not now<t["kickoff"]<=now+timedelta(hours=60):
                reason="WINDOW_NOT_ACTIVE"
            elif not (verified_source_name(row.get("home_team"),t["home"]) and
                      verified_source_name(row.get("away_team"),t["away"])):
                reason="UNVERIFIED_PAIR_IDENTITY"
            else:
                known=str(row.get("league_short") or "") in LEAGUE_PREFIX
                exactly=(home==exact_name(t["home"]) and away==exact_name(t["away"]))
                if known and not league_ok(row.get("league_short"),t.get("league")):
                    reason="KNOWN_LEAGUE_CONFLICT"
                elif not known and not exactly and not (
                    verified_shared_source_name(row["home_team"],t["home"]) is True
                    and verified_shared_source_name(row["away_team"],t["away"]) is True):
                    reason="UNRECOGNIZED_LEAGUE_REQUIRES_TWO_VERIFIED_SHARED_KEYS"
                elif abs((wall-t["kickoff"].astimezone(timezone.utc).replace(tzinfo=None)).total_seconds())>60:
                    reason="KICKOFF_CONFLICT"
            candidates.append(reason or "QUALIFIED")
        if candidates.count("QUALIFIED")==1:
            reasons["one_verified_team_pair"]+=1
        elif candidates.count("QUALIFIED")>1:
            reasons["multiple_canonical_candidates"]+=1
        else:
            reasons["rejected_known_pair_rows"]+=1
            reasons[Counter(candidates).most_common(1)[0][0]]+=1
    return dict(reasons)


def run(now=None, fixture_token=None, helper=None):
    now = now or datetime.now(timezone.utc)
    fixture_token = fixture_token or os.getenv("FOREBET_FIXTURES_OIDC", "")
    targets = canonical_from_oidc(fixture_token, now)
    if len(targets) < 8:
        raise ValueError("TOO_FEW_VERIFIED_FS_FIXTURES")
    dates = source_dates(targets, now)
    candidates, page_proofs, failures = [], [], []
    for date in dates:
        source_url = "https://www.forebet.com/en/football-predictions/predictions-1x2/" + date
        try:
            page_rows, details = load_canonical_candidates(
                source_url, date, targets,
                helper=helper or os.getenv("LOCAL_BROWSER_HELPER", "http://127.0.0.1:8191/v1"))
            candidates.extend(page_rows)
            page_proofs.append({
                "date": date,
                "dom_initial": details.get("initial"),
                "dom_expanded": details.get("expanded"),
                "expand_clicked": details.get("expand_clicked"),
                "capture_mode": details.get("capture_mode"),
                "known_pair_rows": details.get("matched"),
                "parsed_rows": len(page_rows),
                "rendered_html_bytes": details.get("rendered_html_bytes")
            })
        except (ValueError, requests.RequestException, BrowserError) as exc:
            failures.append({"date":date,"error":type(exc).__name__})
    candidates = dedupe_repeated_source_rows(candidates)
    rows, rejected = verified_rows(candidates, targets, now)
    # At most TWO distinct source market pages for each verified 1X2 date.
    # They are optional and never gate the successful daily score publication.
    market_rows=[]
    market_pages=[]
    market_failures=[]
    market_dates=sorted({r["kickoff"][:10] for r in rows})
    if len(market_dates)*2>MAX_MARKET_PAGES:
        raise ValueError("FOREBET_MARKET_PAGE_BUDGET_EXCEEDED")
    for date in market_dates:
        for market,route,parser in (
            ("ou25","under-over-25-goals",parse_ou25),
            ("corners95","corners",parse_corners95),
        ):
            market_url=f"https://www.forebet.com/en/football-predictions/{route}/{date}/by-league"
            try:
                parsed,proof=load_canonical_candidates(
                    market_url,date,targets,
                    helper=helper or os.getenv("LOCAL_BROWSER_HELPER","http://127.0.0.1:8191/v1"),
                    parser=parser,
                )
                market_rows.extend(parsed)
                market_pages.append({
                    "market":market,"date":date,"rows":len(parsed),
                    "capture_mode":proof.get("capture_mode"),
                    "dom_initial":proof.get("initial"),
                    "dom_expanded":proof.get("expanded"),
                    "known_team_pair_rows":proof.get("matched"),
                    "rendered_html_bytes":proof.get("rendered_html_bytes"),
                })
            except (ValueError, requests.RequestException, BrowserError) as exc:
                # Only publish fixed reason codes, not HTML/URLs/credentials.
                reason=str(exc) if isinstance(exc,ValueError) and str(exc).startswith("FOREBET_") else type(exc).__name__
                market_failures.append({
                    "market":market,"date":date,"error":type(exc).__name__,
                    "reason":reason[:100],
                })
    market_coverage=enrich_verified_rows(rows,market_rows)
    provisional, provisional_diagnostics = tentative_rows(candidates, targets, rows, now)
    if len(rows) > MAX_PUBLICATION_ROWS:
        raise ValueError("FOREBET_PUBLICATION_CAPACITY_EXCEEDED")
    summary = {
        "provider":"FOREBET","version":"2.1",
        "dates":dates,"captured_at":now.isoformat(),
        "canonical_source":"VERIFIED_FLASHSCORE_DB",
        "canonical_targets":len(targets),
        "pages_attempted":len(dates),"pages_successful":len(page_proofs),
        "pages_failed":failures,"partial_source_coverage":bool(failures),
        "page_details":page_proofs,
        "source_dom_rows":sum(x["dom_expanded"] or 0 for x in page_proofs),
        "known_team_pair_rows":sum(x["known_pair_rows"] or 0 for x in page_proofs),
        "source_rows_parsed":len(candidates),
        "strict_verified_models":len(rows),
        "market_pages_attempted":len(market_pages)+len(market_failures),
        "market_pages_successful":market_pages,
        "market_pages_failed":market_failures,
        "market_coverage":market_coverage,
        "provisional_one_team_count":len(provisional),
        "provisional_diagnostics":provisional_diagnostics,
        "verified_shared_bridge_matches":sum(1 for row in rows if row["identity_method"]=="VERIFIED_SHARED_PROVIDER_BRIDGE_AND_EXACT_TIME"),
        "verified_two_key_unknown_league_matches":sum(1 for row in rows if row["identity_method"]=="TWO_SHARED_PROVIDER_KEYS_UNKNOWN_LEAGUE_EXACT_UTC_TIME"),
        "verified_existing_alias_matches":sum(1 for row in rows if row["identity_method"]=="VERIFIED_ALIAS_LEAGUE_AND_CALIBRATED_UTC_TIME"),
        "calibrated_utc_offset_minutes":CALIBRATED_DISPLAY_UTC_OFFSET_MINUTES,
        "rejections":rejected,
        "candidate_pair_diagnostics":candidate_pair_diagnostics(candidates,targets,now),
        "source_overlap_diagnostics":source_overlap_diagnostics(candidates,targets,now),
        "target_source_intersection":source_intersection_audit(candidates,targets,rows,now),
        "verified_by_utc_date":{
            date:sum(1 for row in rows if row["kickoff"][:10]==date)
            for date in dates
        },
        "canonical_targets_by_utc_date":{
            date:sum(1 for target in targets if target["kickoff"].date().isoformat()==date)
            for date in dates
        },
        "published":False
    }
    OUT.write_text(json.dumps({"source":"FOREBET","rows":rows},
                              ensure_ascii=False), encoding="utf-8")
    PROVISIONAL_OUT.write_text(json.dumps({
        "source":"FOREBET_PROVISIONAL_RECONCILE_V1",
        "rows":provisional,
        "verified_ids":[x["match_id"] for x in rows],
        "complete_dates":([] if provisional_diagnostics.get("fuzzy_capacity_limited")
            else [x["date"] for x in page_proofs if x["capture_mode"]=="full_page"]),
        "captured_at":now.isoformat(),
    }, ensure_ascii=False), encoding="utf-8")
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
