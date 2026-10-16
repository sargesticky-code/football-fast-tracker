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
    "UCL":"Champions League - League phase",
    "UYL":"UEFA Youth League - ",
    "RuC":"Russian Cup - ",
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
# Exact short league titles now emitted by verified Flashscore fixture rows.
# A short title is corroboration ONLY when the oriented canonical team pair,
# verified provider identity, unique FS fixture and exact kickoff also pass.
# Never fuzzy-match competitions or use a short title as standalone identity.
FLASHscore_EXACT_SHORT_LEAGUES={
    "EPL":"Premier League",
    "Es1":"LaLiga",
    "It1":"Serie A",
    "De1":"Bundesliga",
    "Fr1":"Ligue 1",
    "Ar1":"Liga Profesional - Clausura",
}
# These are validated competition names, not a learned/automatically expanded alias.
def league_ok(code,full):
    prefix=LEAGUE_PREFIX.get(str(code or ""))
    if not prefix or not isinstance(full,str):
        return False
    # Forebet CH is English Championship; Flashscore's verified fixture API
    # now uses the short canonical name without its former country suffix.
    if full==FLASHscore_EXACT_SHORT_LEAGUES.get(str(code or "")):
        return True
    if code=="CH" and full=="Championship":
        return True
    if code=="UCL":
        return full=="Champions League - League phase"
    return full==prefix if prefix=="EPL" else full.startswith(prefix)

def displayed_wall_clock(row):
    """Parse Forebet's visible date/clock WITHOUT inventing its timezone.

    Forebet publishes user-adjustable display clocks. The HTML date attribute
    and visible clock can even straddle different days. Only the visible full
    date+clock is used for source-to-canonical cohort corroboration.
    """
    stamp=str(row.get("kickoff_text") or "").strip()
    day=str(row.get("match_date") or "")
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}",day):
        return None
    for fmt in ("%m/%d/%Y %I:%M %p","%m/%d/%Y %H:%M",
                "%d/%m/%Y %I:%M %p","%d/%m/%Y %H:%M"):
        try:
            dt=datetime.strptime(stamp,fmt)
            # The HTML <time datetime> is a different clock/basis from the
            # complete human-visible date_bah. Forebet rows near midnight
            # legitimately cross a calendar boundary. A discrepancy of one
            # day is tolerable only because the downstream publisher demands
            # both verified teams and an exact Flashscore UTC kickoff.
            # Never infer a time when the displayed full date is absent.
            if abs((dt.date()-datetime.fromisoformat(day).date()).days)<=1:
                return dt
        except ValueError:
            continue
    return None

def displayed_utc(row):
    """Legacy parse helper for tests; **not** evidence of actual UTC timezone."""
    wall=displayed_wall_clock(row)
    return wall.replace(tzinfo=timezone.utc) if wall else None

def canonical_feed_matches(payload, now):
    """Require exact Flashscore fixture provenance, not a single response label.

    The canonical API can temporarily serve the vetted lightweight recovery
    envelope. Trust its individual rows only when they attest exact FS fixture
    identity and contain an actual timezone-aware kickoff.
    """
    if not isinstance(payload,dict) or not isinstance(payload.get("matches"),list):
        raise ValueError("canonical feed missing matches")
    src=payload.get("source")
    if src not in ("flashscore-single-rpc-canonical",
                   "supabase-lightweight-enrichment-recovery"):
        raise ValueError("canonical authority feed not verified")
    if src=="supabase-lightweight-enrichment-recovery" and payload.get("recoveryMode") not in (
        "AUTHORITY_ONLY","LIGHTWEIGHT_CANONICAL_EVIDENCE"):
        raise ValueError("recovery mode not verified")
    # A recent generatedAt proves response currency, not the source fixture
    # identity; both checks remain independent.
    generated=payload.get("generatedAt")
    if not isinstance(generated,str):
        raise ValueError("canonical response timestamp missing")
    try:
        issued=datetime.fromisoformat(generated.replace("Z","+00:00"))
    except ValueError as exc:
        raise ValueError("canonical response timestamp invalid") from exc
    if issued.tzinfo is None or not -60 <= (now-issued).total_seconds() <= 1200:
        raise ValueError("canonical response stale or future")
    verified=[]
    for m in payload["matches"]:
        if not isinstance(m,dict) or not re.fullmatch(r"FS:[A-Za-z0-9_-]{5,32}",str(m.get("id") or "")):
            continue
        context=m.get("sourceContext")
        if not isinstance(context,dict) or context.get("identityStatus")!="EXACT_CANONICAL_PROVIDER_FIXTURE":
            continue
        verified.append(m)
    if len(verified)<8:
        raise ValueError("insufficient individually verified canonical fixtures")
    return verified

def verified_rows(raw, targets, now):
    """One verified team+league+time ID, with a COHORT-proven display offset.

    A screen clock isn't UTC merely because it has no suffix. Corroborate one
    common offset against at least eight distinct canonical fixture IDs from
    three competitions. Ignore other offsets; refuse ambiguous/duplicate IDs.
    """
    catalog={}
    for t in targets:
        if not t.get("match_id") or t.get("kickoff") is None:
            continue
        for home_key in source_forms(t["home"]):
            for away_key in source_forms(t["away"]):
                catalog.setdefault((home_key,away_key),[]).append(t)
    candidates=[]
    rejected=Counter()
    for row in raw:
        fields=model_fields(row)
        wall=displayed_wall_clock(row)
        if not fields or wall is None:
            rejected["fields_or_clock"]+=1
            continue
        key=(exact_name(row.get("home_team")),exact_name(row.get("away_team")))
        possible=[t for t in catalog.get(key,[]) if
                  verified_source_name(row.get("home_team"),t["home"]) and
                  verified_source_name(row.get("away_team"),t["away"]) and
                  league_ok(row.get("league_short"),t.get("league")) and
                  t["kickoff"]>now and t["kickoff"]<=now+timedelta(hours=48)]
        if len(possible)!=1:
            rejected["not_unique_league_identity"]+=1
            continue
        t=possible[0]
        # Difference between source's *naive displayed clock* and the
        # canonical absolute instant, expressed in wall-clock minutes.
        delta=(wall - t["kickoff"].astimezone(timezone.utc).replace(tzinfo=None)).total_seconds()
        minutes=round(delta/60)
        # Civil offsets have 15-minute granularity, UTC-12 through UTC+14.
        if not (-720<=minutes<=840 and abs(delta-minutes*60)<=60 and minutes%15==0):
            rejected["clock_outside_civil_offset"]+=1
            continue
        candidates.append((row,t,wall,fields,minutes))
    grouped={}
    for entry in candidates:
        grouped.setdefault(entry[4],[]).append(entry)
    # Never silently pick the first apparent timezone if multiple disagree.
    validated=[]
    for offset,entries in grouped.items():
        ids=[t["match_id"] for _,t,_,_,_ in entries]
        leagues={t["league"] for _,t,_,_,_ in entries}
        if len(entries)>=8 and len(leagues)>=3 and len(set(ids))==len(ids):
            validated.append((offset,entries))
    if len(validated)!=1:
        return [],{"candidate_models":len(candidates),"verified":0,
                   "leagues":0,"reason":"COHORT_TIME_NOT_CORROBORATED",
                   "observed_clock_offsets":{str(o):len(v) for o,v in sorted(grouped.items())},
                   "rejections":dict(rejected)}
    offset,proposals=validated[0]
    if len(proposals)*5 < len(candidates)*4:
        return [],{"candidate_models":len(candidates),"verified":0,
                   "leagues":len({t["league"] for _,t,_,_,_ in proposals}),
                   "reason":"AMBIGUOUS_SOURCE_CLOCK_COHORT",
                   "observed_clock_offsets":{str(o):len(v) for o,v in sorted(grouped.items())},
                   "rejections":dict(rejected)}
    unique_ids={t["match_id"] for _,t,_,_,_ in proposals}
    if len(unique_ids)!=len(proposals):
        return [],{"candidate_models":len(candidates),"verified":0,
                   "leagues":0,"reason":"DUPLICATE_CANONICAL_MATCHES",
                   "rejections":dict(rejected)}
    verified=[]
    seen_urls=set()
    for row,t,wall,fields,_ in proposals:
        uri=row["forebet_detail_url"]
        if uri in seen_urls:
            return [],{"candidate_models":len(candidates),"verified":0,
                       "leagues":0,"reason":"DUPLICATE_FOREBET_SOURCE_EVENTS",
                       "rejections":dict(rejected)}
        seen_urls.add(uri)
        exact_pair=(exact_name(row["home_team"])==exact_name(t["home"]) and
                    exact_name(row["away_team"])==exact_name(t["away"]))
        verified.append({
            "match_id":t["match_id"],"captured_at":now.isoformat(),
            "kickoff":t["kickoff"].isoformat(),
            "canonical_home":t["home"],"canonical_away":t["away"],
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
            "source_event_time":(wall-timedelta(minutes=offset)).replace(
                tzinfo=timezone.utc).isoformat(),
            "source_event_time_basis":"CROSS_LEAGUE_COHORT_CORROBORATED_DISPLAY_OFFSET",
            "source_display_offset_minutes":offset,
            "identity_method":("EXACT_TEAMS_LEAGUE_AND_CORROBORATED_TIME"
                               if exact_pair else "VERIFIED_ALIAS_LEAGUE_AND_CORROBORATED_TIME")
        })
    return verified,{"candidate_models":len(candidates),"verified":len(verified),
                     "leagues":len({t["league"] for _,t,_,_,_ in proposals}),
                     "clock_offset_minutes":offset,
                     "source_clock_corroboration":"AT_LEAST_EIGHT_MATCHES_THREE_LEAGUES",
                     "observed_clock_offsets":{str(o):len(v) for o,v in sorted(grouped.items())},
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
    matches=canonical_feed_matches(data,now)
    targets=canonical_targets(matches,now)
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
