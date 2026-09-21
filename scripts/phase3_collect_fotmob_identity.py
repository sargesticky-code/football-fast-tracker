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

from phase3.external_identity import choose_candidate, ranked_candidates, coverage_diagnostic
from phase3.hkjc_authority import evaluate_authority

AUTH=Path("data/phase3_hkjc_authority.json")
EVIDENCE=Path("data/phase3_identity_evidence.jsonl")


def eligible_rows(payload: dict) -> tuple[list[dict], str, float | None]:
    """Reuse Layer 1 authority contract; never reimplement live eligibility here."""
    result=evaluate_authority(
        payload.get("rows") or [],
        source_fetched_at=payload.get("fetched_at"),
        now=datetime.now(timezone.utc),
    )
    return [dict(r) for r in result.rows if r.get("phase3_eligible")], result.health, result.snapshot_age_seconds


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


def _names(hk: dict) -> tuple[str, str]:
    home=str(hk.get("home_en") or hk.get("home") or "").strip()
    away=str(hk.get("away_en") or hk.get("away") or "").strip()
    return home,away


def main() -> int:
    if not AUTH.exists():
        print("PHASE3_LAYER2 source_gap=NO_AUTHORITY_SNAPSHOT requests=0")
        return 2
    authority=json.loads(AUTH.read_text(encoding="utf-8"))
    eligible,authority_health,authority_age=eligible_rows(authority)
    age="NA" if authority_age is None else f"{authority_age:.1f}"
    if not eligible:
        print(
            f"PHASE3_LAYER2 eligible=0 requests=0 evidence_added=0 "
            f"authority_health={authority_health} authority_age_seconds={age}"
        )
        return 0

    dates=sorted({str(r.get("kickoff_hkt") or "")[:10].replace("-","") for r in eligible if r.get("kickoff_hkt")})
    if len(dates)!=1:
        print(f"PHASE3_LAYER2 eligible={len(eligible)} requests=0 source_gap=DATE_AMBIGUITY")
        return 2
    board=fotmob_board(dates[0])
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    additions=[]; unresolved=0
    for hk in eligible:
        event=hk.get("hkjc_event_id")
        home,away=_names(hk)
        if not home or not away:
            unresolved+=1
            print(
                f"PHASE3_IDENTITY event={event} status=UNRESOLVED reason=HKJC_NAME_GAP "
                f"home_present={int(bool(home))} away_present={int(bool(away))} candidates=0"
            )
            continue
        c,reason=choose_candidate(hk,board)
        if not c:
            unresolved+=1
            ranked=ranked_candidates(hk,board,limit=3)
            print(
                f"PHASE3_IDENTITY event={event} status=UNRESOLVED reason={reason} "
                f"hkjc_fixture={home}|{away} candidates={len(ranked)}"
            )
            for rank,x in enumerate(ranked,1):
                print(
                    f"PHASE3_IDENTITY_DIAG event={event} rank={rank} "
                    f"external={x.source_match_id} confidence={x.confidence:.3f} "
                    f"home_score={x.home_score:.3f} away_score={x.away_score:.3f} "
                    f"drift_seconds={x.kickoff_drift_seconds} "
                    f"fixture={x.home}|{x.away} competition={x.competition}"
                )
            if not ranked:
                coverage=coverage_diagnostic(hk,board,limit=3)
                for rank,x in enumerate(coverage,1):
                    drift="NA" if x["kickoff_drift_seconds"] is None else x["kickoff_drift_seconds"]
                    print(
                        f"PHASE3_IDENTITY_COVERAGE event={event} rank={rank} "
                        f"external={x['source_match_id']} name_score={x['name_score']:.3f} "
                        f"home_score={x['home_score']:.3f} away_score={x['away_score']:.3f} "
                        f"drift_seconds={drift} fixture={x['home']}|{x['away']} "
                        f"competition={x['competition']}"
                    )
            continue
        additions.append(json.dumps({
            "hkjc_event_id":str(event),"source":"FOTMOB",
            "source_match_id":c.source_match_id,"confidence":c.confidence,"observed_at":now,
            "home":c.home,"away":c.away,"kickoff":c.kickoff,"competition":c.competition,
        },ensure_ascii=False))
        print(f"PHASE3_IDENTITY event={event} external={c.source_match_id} confidence={c.confidence:.3f} status=CANDIDATE")
    if additions:
        EVIDENCE.parent.mkdir(parents=True,exist_ok=True)
        with EVIDENCE.open("a",encoding="utf-8") as fh:
            fh.write("\n".join(additions)+"\n")
    print(f"PHASE3_LAYER2 eligible={len(eligible)} board_rows={len(board)} requests=1 evidence_added={len(additions)} unresolved={unresolved}")
    return 0

if __name__=="__main__": raise SystemExit(main())
