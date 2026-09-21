#!/usr/bin/env python3
"""Collect Phase 3 Layer 2 FotMob identity evidence for HKJC-eligible rows.

At most one FotMob daily-board request is made per execution, regardless of the
number of eligible HKJC matches. No request is made when HKJC has no eligible
rows. Ambiguous/weak matches are reported but never persisted as evidence.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from phase3.external_identity import choose_candidate, ranked_candidates

AUTH=Path("data/phase3_hkjc_authority.json")
EVIDENCE=Path("data/phase3_identity_evidence.jsonl")


def eligible_rows(payload: dict) -> list[dict]:
    out=[]
    for r in payload.get("rows") or []:
        selling=str(r.get("pool_status") or r.get("selling_status") or "").upper()
        status=str(r.get("status") or "").upper()
        live=any(x in status for x in ("FIRSTHALF","SECONDHALF","INPLAY","EXTRATIME","PENALTY"))
        if selling=="SELLINGSTARTED" and live and r.get("hkjc_event_id") and r.get("match_id"):
            out.append(r)
    return out


def fotmob_board(date: str) -> list[dict]:
    url=f"https://www.fotmob.com/api/data/matches?date={date}"
    req=Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    with urlopen(req,timeout=12) as resp:
        data=json.load(resp)
    rows=[]
    for league in data.get("leagues") or []:
        competition=(league.get("primaryName") or league.get("name") or "")
        for m in league.get("matches") or []:
            home=m.get("home") or {}; away=m.get("away") or {}
            rows.append({
                "id":m.get("id"),
                "home":home.get("name") or home.get("longName") or "",
                "away":away.get("name") or away.get("longName") or "",
                "kickoff":m.get("status",{}).get("utcTime") or m.get("timeTS") or "",
                "competition":competition,
            })
    return rows


def main() -> int:
    if not AUTH.exists():
        print("PHASE3_LAYER2 source_gap=NO_AUTHORITY_SNAPSHOT requests=0")
        return 2
    authority=json.loads(AUTH.read_text(encoding="utf-8"))
    eligible=eligible_rows(authority)
    if not eligible:
        print("PHASE3_LAYER2 eligible=0 requests=0 evidence_added=0")
        return 0

    dates=sorted({str(r.get("kickoff_hkt") or "")[:10].replace("-","") for r in eligible if r.get("kickoff_hkt")})
    if len(dates)!=1:
        print(f"PHASE3_LAYER2 eligible={len(eligible)} requests=0 source_gap=DATE_AMBIGUITY")
        return 2
    board=fotmob_board(dates[0])
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    additions=[]; unresolved=0
    for hk in eligible:
        c,reason=choose_candidate(hk,board)
        if not c:
            unresolved+=1
            ranked=ranked_candidates(hk,board,limit=3)
            print(f"PHASE3_IDENTITY event={hk.get('hkjc_event_id')} status=UNRESOLVED reason={reason} candidates={len(ranked)}")
            for rank,x in enumerate(ranked,1):
                print(
                    f"PHASE3_IDENTITY_DIAG event={hk.get('hkjc_event_id')} rank={rank} "
                    f"external={x.source_match_id} confidence={x.confidence:.3f} "
                    f"home_score={x.home_score:.3f} away_score={x.away_score:.3f} "
                    f"drift_seconds={x.kickoff_drift_seconds} "
                    f"fixture={x.home}|{x.away} competition={x.competition}"
                )
            continue
        additions.append(json.dumps({
            "hkjc_event_id":str(hk.get("hkjc_event_id")),"source":"FOTMOB",
            "source_match_id":c.source_match_id,"confidence":c.confidence,"observed_at":now,
            "home":c.home,"away":c.away,"kickoff":c.kickoff,"competition":c.competition,
        },ensure_ascii=False))
        print(f"PHASE3_IDENTITY event={hk.get('hkjc_event_id')} external={c.source_match_id} confidence={c.confidence:.3f} status=CANDIDATE")
    if additions:
        EVIDENCE.parent.mkdir(parents=True,exist_ok=True)
        with EVIDENCE.open("a",encoding="utf-8") as fh:
            fh.write("\n".join(additions)+"\n")
    print(f"PHASE3_LAYER2 eligible={len(eligible)} board_rows={len(board)} requests=1 evidence_added={len(additions)} unresolved={unresolved}")
    return 0

if __name__=="__main__": raise SystemExit(main())
