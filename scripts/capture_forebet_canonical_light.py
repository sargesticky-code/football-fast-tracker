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
    build_verified_rows, exact_name, model_fields)
from probe_forebet_upstream_framework import expand_with_normal_browser
from scrape_forebet import parse_forebet_rows

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
    """UTC provenance is independent clock corroboration, never HTML's date-only time."""
    catalog={}
    for t in targets:
        if not t.get("match_id") or t.get("kickoff") is None:continue
        k=(exact_name(t["home"]),exact_name(t["away"]))
        catalog.setdefault(k,[]).append(t)
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
               league_ok(row.get("league_short"),t.get("league")) and
               abs((wall-t["kickoff"]).total_seconds())<=60 and
               t["kickoff"]>now and t["kickoff"]<=now+timedelta(hours=48)]
        if len(valid)!=1:
            rejected["not_unique_league_time_identity"]+=1
            continue
        proposals.append((row,valid[0],wall))
    # Do not infer provider clock format from 1-2 accidental matches.
    unique_leagues={t["league"] for _,t,_ in proposals}
    unique_ids={t["match_id"] for _,t,_ in proposals}
    if len(proposals)<8 or len(unique_leagues)<3 or len(unique_ids)!=len(proposals):
        return [],{"candidate_models":len(proposals),"verified":0,
                   "leagues":len(unique_leagues),"reason":"COHORT_TIME_NOT_CORROBORATED",
                   "rejections":dict(rejected)}
    adapted=[]
    source_urls=set()
    for row,t,wall in proposals:
        uri=row.get("forebet_detail_url") or ""
        if uri in source_urls:
            rejected["duplicate_source_event"]+=1
            continue
        source_urls.add(uri)
        r=dict(row)
        r["source_kickoff_iso"]=wall.isoformat()
        adapted.append(r)
    payload=build_verified_rows(targets,adapted,now)
    by_id={x["match_id"]:x for x in payload}
    verified=[]
    for row,t,_ in proposals:
        x=by_id.get(t["match_id"])
        if not x or x["match_id"] in {z["match_id"] for z in verified}:
            continue
        x["canonical_league"]=t["league"]
        x["source_league"]=row.get("league_short")
        x["source_event_time_basis"]="SOURCE_DISPLAYED_CLOCK_CORROBORATED_WITH_CANONICAL_UTC"
        x["identity_method"]="EXACT_TEAMS_LEAGUE_AND_CORROBORATED_TIME"
        verified.append(x)
    return verified,{"candidate_models":len(proposals),"verified":len(verified),
                      "leagues":len(unique_leagues),"clock_offset_minutes":0,
                      "rejections":dict(rejected)}

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
    helper=os.getenv("LOCAL_BROWSER_HELPER","http://127.0.0.1:8191/v1")
    req=sess.post(helper,json={"cmd":"request.get","url":url,"maxTimeout":55000},
                  timeout=65,headers={"Content-Type":"application/json"})
    req.raise_for_status()
    response=req.json()
    solution=response.get("solution") or {}
    html=solution.get("response") or ""
    if response.get("status")!="ok" or solution.get("status")!=200 or not isinstance(html,str) or len(html)>2000000:
        raise ValueError("source page unavailable or over bounded limit")
    if "rcnt" not in html: raise ValueError("source page contains no fixtures")
    # Page selection implemented in browser helper prototype; do not retain huge HTML.
    rows,details=expand_with_normal_browser(url,solution,date)
    output,info=verified_rows(rows,targets,now)
    proof={"provider":"FOREBET","captured_at":now.isoformat(),"date":date,
           "canonical_targets":len(targets),"source_page_initial_rows":len(parse_forebet_rows(html,date)),
           "source_page_expanded_rows":details.get("expanded_rows"),
           "strict_matched_models":len(output),**info,
           "scheduled":False,"published":False}
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
