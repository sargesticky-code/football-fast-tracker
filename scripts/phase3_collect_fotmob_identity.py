#!/usr/bin/env python3
"""Collect Phase 3 Layer 2 external identity evidence for HKJC-eligible rows.

FotMob is primary. Sofascore is retained as a coverage-gap fallback with
persistent cooldown; ESPN is a request-efficient third board fallback when
Sofascore is unavailable. External sources never create HKJC eligibility.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from phase3.external_identity import choose_candidate, ranked_candidates, coverage_diagnostic, classify_unresolved
from phase3.hkjc_authority import evaluate_authority
from phase3.sofascore_identity import normalize_board as normalize_sofascore_board
from phase3.espn_identity import normalize_board as normalize_espn_board
AUTH=Path("data/phase3_hkjc_authority.json"); EVIDENCE=Path("data/phase3_identity_evidence.jsonl"); SOURCE_HEALTH=Path("data/phase3_identity_source_health.json")
SOFASCORE_COOLDOWN_SECONDS=6*60*60

def eligible_rows(payload):
    r=evaluate_authority(payload.get("rows") or [],source_fetched_at=payload.get("fetched_at"),now=datetime.now(timezone.utc)); return [dict(x) for x in r.rows if x.get("phase3_eligible")],r.health,r.snapshot_age_seconds

def _get(url):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    with urlopen(req,timeout=12) as resp: return json.load(resp)

def fotmob_board(date):
    data=_get(f"https://www.fotmob.com/api/data/matches?date={date}"); rows=[]
    for league in data.get("leagues") or []:
        competition=league.get("primaryName") or league.get("name") or ""
        for m in league.get("matches") or []:
            h=m.get("home") or {}; a=m.get("away") or {}; rows.append({"id":m.get("id"),"home":h.get("name") or h.get("longName") or "","away":a.get("name") or a.get("longName") or "","kickoff":m.get("status",{}).get("utcTime") or m.get("timeTS") or "","competition":competition})
    return rows

def sofascore_board(date):
    iso=f"{date[:4]}-{date[4:6]}-{date[6:8]}"; last=None
    for url in [f"https://www.sofascore.com/api/v1/sport/football/scheduled-events/{iso}",f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{iso}"]:
        try: return normalize_sofascore_board(_get(url))
        except HTTPError as exc:
            last=exc
            if exc.code not in {403,404,429}: raise
    if last: raise last
    return []

def espn_board(date):
    return normalize_espn_board(_get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={date}&limit=1000"))

def _load_health():
    try:return json.loads(SOURCE_HEALTH.read_text(encoding="utf-8"))
    except (FileNotFoundError,json.JSONDecodeError):return {}
def _save_health(s): SOURCE_HEALTH.parent.mkdir(parents=True,exist_ok=True); SOURCE_HEALTH.write_text(json.dumps(s,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def _cooldown(s,now):
    raw=(s.get("SOFASCORE") or {}).get("blocked_at")
    if not raw:return False,0
    try:b=datetime.fromisoformat(str(raw).replace("Z","+00:00")).astimezone(timezone.utc)
    except ValueError:return False,0
    age=max(0,(now-b).total_seconds()); return age<SOFASCORE_COOLDOWN_SECONDS,age

def main():
    if not AUTH.exists(): print("PHASE3_LAYER2 source_gap=NO_AUTHORITY_SNAPSHOT requests=0"); return 2
    authority=json.loads(AUTH.read_text(encoding="utf-8")); eligible,health,age=eligible_rows(authority)
    if not eligible: print(f"PHASE3_LAYER2 eligible=0 requests=0 evidence_added=0 authority_health={health}"); return 0
    dates=sorted({str(r.get("kickoff_hkt") or "")[:10].replace("-","") for r in eligible if r.get("kickoff_hkt")})
    if len(dates)!=1: print(f"PHASE3_LAYER2 eligible={len(eligible)} requests=0 source_gap=DATE_AMBIGUITY"); return 2
    board=fotmob_board(dates[0]); nowdt=datetime.now(timezone.utc).replace(microsecond=0); now=nowdt.isoformat(); state=_load_health(); additions=[]; unresolved=0; sofa=[]; espn=[]; sofa_attempted=False; espn_attempted=False; sofa_req=0; espn_req=0
    for hk in eligible:
        event=hk.get("hkjc_event_id"); home=str(hk.get("home_en") or hk.get("home") or "").strip(); away=str(hk.get("away_en") or hk.get("away") or "").strip()
        if not home or not away: unresolved+=1; print(f"PHASE3_IDENTITY event={event} status=UNRESOLVED reason=HKJC_NAME_GAP"); continue
        candidate,reason=choose_candidate(hk,board); source="FOTMOB"
        if not candidate and classify_unresolved(hk,board)=="SOURCE_COVERAGE_GAP":
            cool,cage=_cooldown(state,nowdt)
            if cool: print(f"PHASE3_IDENTITY_FALLBACK source=SOFASCORE status=COOLDOWN age_seconds={cage:.0f}")
            elif not sofa_attempted:
                sofa_attempted=True; sofa_req=1
                try: sofa=sofascore_board(dates[0]); state.pop("SOFASCORE",None); _save_health(state)
                except HTTPError as exc: state["SOFASCORE"]={"status":"HTTP_BLOCKED","http_status":exc.code,"blocked_at":now}; _save_health(state); print(f"PHASE3_IDENTITY_FALLBACK source=SOFASCORE status=SOURCE_HTTP_ERROR http_status={exc.code}")
            candidate,reason=choose_candidate(hk,sofa); source="SOFASCORE"
            if not candidate:
                if not espn_attempted:
                    espn_attempted=True; espn_req=1
                    try: espn=espn_board(dates[0]); print(f"PHASE3_IDENTITY_FALLBACK source=ESPN status=OK board_rows={len(espn)}")
                    except Exception as exc: print(f"PHASE3_IDENTITY_FALLBACK source=ESPN status=SOURCE_ERROR error={type(exc).__name__}")
                candidate,reason=choose_candidate(hk,espn); source="ESPN"
        if candidate:
            additions.append(json.dumps({"hkjc_event_id":str(event),"source":source,"source_match_id":candidate.source_match_id,"confidence":candidate.confidence,"observed_at":now,"home":candidate.home,"away":candidate.away,"kickoff":candidate.kickoff,"competition":candidate.competition},ensure_ascii=False)); print(f"PHASE3_IDENTITY event={event} source={source} external={candidate.source_match_id} confidence={candidate.confidence:.3f} status=CANDIDATE"); continue
        unresolved+=1; diag=classify_unresolved(hk,board); ranked=ranked_candidates(hk,board,limit=3); print(f"PHASE3_IDENTITY event={event} status=UNRESOLVED reason={diag} matcher_reason={reason} hkjc_fixture={home}|{away} candidates={len(ranked)}")
        if not ranked:
            for rank,x in enumerate(coverage_diagnostic(hk,board,limit=3),1): print(f"PHASE3_IDENTITY_COVERAGE event={event} rank={rank} external={x['source_match_id']} name_score={x['name_score']:.3f} drift_seconds={x['kickoff_drift_seconds']} fixture={x['home']}|{x['away']}")
    if additions:
        EVIDENCE.parent.mkdir(parents=True,exist_ok=True)
        with EVIDENCE.open("a",encoding="utf-8") as fh: fh.write("\n".join(additions)+"\n")
    print(f"PHASE3_LAYER2 eligible={len(eligible)} board_rows={len(board)} fotmob_requests=1 sofascore_requests={sofa_req} espn_requests={espn_req} evidence_added={len(additions)} unresolved={unresolved}"); return 0
if __name__=="__main__": raise SystemExit(main())
