#!/usr/bin/env python3
"""One-page, source-backed Forebet 1X2 capture for existing canonical fixtures.

Private dry run: no credentials in output, no database writes, no retries, no
schedule. Original implementation using the verified existing browser-helper
prototype; the old HKJC CSV is not read or used for mapping.
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
from forebet_canonical_source_probe import (API, canonical_targets,
    exact_name, model_fields)
from forebet_verified_aliases import source_forms, verified_source_name

HKT=timezone(timedelta(hours=8))
OUT=Path("/tmp/ft-forebet-verified-only.json")
SUMMARY=Path("/tmp/ft-forebet-verified-summary.json")
LEAGUE_PREFIX={
    "EPL":"EPL",
    "CH":"ChampionshipENGLAND:",
    "Sc1":"PremiershipSCOTLAND:",
    "Es1":"LaLigaSPAIN:",
    "It1":"Serie AITALY:",
    "De1":"BundesligaGERMANY:",
    "Fr1":"Ligue 1FRANCE:",
    # Recorded in the 2026-10-10 25-pair official-source clock cohort.
    # Expansion uses the SAME page fetch; never fuzzy-learns new league names.
    "Bg1":"efbet LeagueBULGARIA:",
    "Cz1":"Chance LigaCZECH REPUBLIC:",
    "Gr1":"Super LeagueGREECE:",
    "Hr1":"HNLCROATIA:",
    "Ar1":"Liga Profesional - ClausuraARGENTINA:",
    "Cl1":"Liga de PrimeraCHILE:",
    "Bo1":"Division ProfesionalBOLIVIA:",
}
# These are validated competition names, not a learned/automatically expanded alias.
def league_ok(code,full):
    prefix=LEAGUE_PREFIX.get(str(code or ""))
    if not prefix or not isinstance(full,str):
        return False
    return full==prefix if prefix=="EPL" else full.startswith(prefix)

def displayed_utc(row):
    """Only parse an actually displayed date+clock. No time zone is invented."""
    stamp=str(row.get("kickoff_text") or "").strip()
    day=str(row.get("match_date") or "")
    for f in ("%m/%d/%Y %I:%M %p","%m/%d/%Y %H:%M",
              "%d/%m/%Y %I:%M %p","%d/%m/%Y %H:%M"):
        try:
            dt=datetime.strptime(stamp,f)
            if dt.date().isoformat()==day: return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None

def verified_rows(raw, targets, now):
    """One strict team+league+minute match; source names always preserved."""
    catalog={}
    for t in targets:
        if not t.get("match_id") or t.get("kickoff") is None:
            continue
        for home_key in source_forms(t["home"]):
            for away_key in source_forms(t["away"]):
                catalog.setdefault((home_key,away_key),[]).append(t)
    proposals=[]
    rejected=Counter()
    for row in raw:
        fields=model_fields(row)
        wall=displayed_utc(row)
        if not fields or not wall:
            rejected["fields_or_clock"]+=1
            continue
        key=(exact_name(row.get("home_team")),exact_name(row.get("away_team")))
        valid=[t for t in catalog.get(key,[]) if
               verified_source_name(row.get("home_team"),t["home"]) and
               verified_source_name(row.get("away_team"),t["away"]) and
               league_ok(row.get("league_short"),t.get("league")) and
               abs((wall-t["kickoff"]).total_seconds())<=60 and
               t["kickoff"]>now and t["kickoff"]<=now+timedelta(hours=48)]
        if len(valid)!=1:
            rejected["not_unique_league_time_identity"]+=1
            continue
        proposals.append((row,valid[0],wall,fields))
    unique_leagues={t["league"] for _,t,_,_ in proposals}
    unique_ids={t["match_id"] for _,t,_,_ in proposals}
    # A time/identity cohort protects against a page timezone or parser drift.
    if len(proposals)<8 or len(unique_leagues)<3 or len(unique_ids)!=len(proposals):
        return [],{"candidate_models":len(proposals),"verified":0,
                   "leagues":len(unique_leagues),"reason":"COHORT_TIME_NOT_CORROBORATED",
                   "rejections":dict(rejected)}
    verified=[]
    seen_urls=set()
    for row,t,wall,fields in proposals:
        uri=row["forebet_detail_url"]
        if uri in seen_urls:
            rejected["duplicate_source_event"]+=1
            continue
        seen_urls.add(uri)
        exact_pair=(exact_name(row["home_team"])==exact_name(t["home"]) and
                    exact_name(row["away_team"])==exact_name(t["away"]))
        verified.append({
            "match_id":t["match_id"],"captured_at":now.isoformat(),
            "kickoff":t["kickoff"].isoformat(),
            "canonical_home":t["home"],"canonical_away":t["away"],
            # These are the ACTUAL official provider names, never rewritten.
            "source_home":row["home_team"],"source_away":row["away_team"],
            "home":fields["home"],"draw":fields["draw"],"away":fields["away"],
            "pick":fields["pick"],"score":fields["score"],
            "avg_goals":fields["avg_goals"],
            "match_score":0.995 if exact_pair else 0.985,
            "match_date":str(row.get("match_date") or ""),
            "kickoff_text":str(row.get("kickoff_text") or ""),
            "league":str(row.get("league_short") or ""),
            "canonical_league":t["league"],
            "source_league":str(row.get("league_short") or ""),
            "source_event_url":uri,
            "source_event_time":wall.isoformat(),
            "source_event_time_basis":"SOURCE_DISPLAYED_CLOCK_CORROBORATED_WITH_CANONICAL_UTC",
            "identity_method":("EXACT_TEAMS_LEAGUE_AND_CORROBORATED_TIME"
                               if exact_pair else "VERIFIED_ALIAS_LEAGUE_AND_CORROBORATED_TIME"),
        })
    return verified,{"candidate_models":len(proposals),"verified":len(verified),
                     "leagues":len(unique_leagues),"clock_offset_minutes":0,
                     "verified_alias_matches":sum(x["identity_method"].startswith("VERIFIED_ALIAS") for x in verified),
                     "rejections":dict(rejected)}

def source_coverage_counts(details, targets, source_date, candidate_rows, verified):
    """Read-only accounting: expanded DOM != matched canonical candidate rows."""
    target_day_count=sum(
        t["kickoff"].astimezone(HKT).strftime("%Y-%m-%d")==source_date
        for t in targets
    )
    parsed=details.get("parsed_candidates")
    matched=details.get("matched")
    return {
        "canonical_targets_on_captured_day":target_day_count,
        "canonical_targets_on_other_days":len(targets)-target_day_count,
        "source_dom_rows_expanded":details.get("expanded"),
        "source_pairs_matching_known_canonical_names":matched,
        "source_rows_parsed_from_matched_pairs":parsed,
        "normalized_candidate_rows":len(candidate_rows),
        "strict_accepted_candidate_rows":len(verified),
        "candidate_rows_not_accepted":max(0,len(candidate_rows)-len(verified)),
        # A thousand expanded global fixtures are NOT a thousand rejected IDs.
        "accounting_semantics":"DOM_GLOBAL_VS_PRE_FILTERED_CANDIDATES"
    }

def capture():
    now=datetime.now(timezone.utc)
    sess=requests.Session()
    api=sess.get(API,timeout=18)
    api.raise_for_status()
    data=api.json()
    if data.get("source")!="flashscore-single-rpc-canonical":
        raise ValueError("canonical authority feed not verified")
    targets=canonical_targets(data.get("matches",[]),now)
    if len(targets)<8:
        raise ValueError("insufficient canonical targets")
    # One official date page; no additional boards or brute-force pagination.
    date=(now.astimezone(HKT)+timedelta(days=1)).strftime("%Y-%m-%d")
    url="https://www.forebet.com/en/football-predictions/predictions-1x2/"+date
    from forebet_browser_source import load_canonical_candidates
    helper=os.getenv("LOCAL_BROWSER_HELPER","http://127.0.0.1:8191/v1")
    rows,details=load_canonical_candidates(url,date,targets,helper=helper)
    output,info=verified_rows(rows,targets,now)
    proof={"provider":"FOREBET","captured_at":now.isoformat(),"date":date,
           "canonical_targets":len(targets),"source_page_initial_rows":details.get("initial"),
           "source_page_expanded_rows":details.get("expanded"),
           "strict_matched_models":len(output),
           **source_coverage_counts(details,targets,date,rows,output),
           **info,"scheduled":False,"published":False}
    SUMMARY.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding="utf-8")
    OUT.write_text(json.dumps({"source":"FOREBET","rows":output},ensure_ascii=False),encoding="utf-8")
    print("FOREBET_CANONICAL_STRICT_PROOF "+json.dumps(proof,ensure_ascii=False),flush=True)
    print("FOREBET_CANONICAL_VERIFIED_SAMPLES "+json.dumps([{
      "id":x["match_id"],"league":x["canonical_league"],"match":x["canonical_home"]+"-"+x["canonical_away"],
      "kickoff":x["kickoff"],"hda":[x["home"],x["draw"],x["away"]],
      "score":x["score"],"avg_goals":x["avg_goals"]} for x in output[:12]],ensure_ascii=False),flush=True)
    return 0 if output else 3

if __name__=="__main__":
    try:
        sys.exit(capture())
    except (ValueError,TypeError,requests.RequestException) as exc:
        print("FOREBET_CANONICAL_SOURCE_UNAVAILABLE "+type(exc).__name__+" "+str(exc)[:180],file=sys.stderr)
        sys.exit(2)
