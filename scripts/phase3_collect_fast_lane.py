#!/usr/bin/env python3
"""Collect a lightweight FotMob heartbeat and join only VERIFIED Layer-2 IDs."""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from phase3.fast_lane import normalize_fotmob_board, join_verified_fast_rows

REGISTRY=ROOT/'data/phase3_live_identity_map.json'
OUT=ROOT/'data/phase3_fast_snapshot.json'
LAST_GOOD=ROOT/'data/phase3_fast_last_good.json'
URL='https://www.fotmob.com/api/matches?date={date}'


def load_rows(path):
    if not path.exists(): return []
    payload=json.loads(path.read_text())
    return payload.get('rows',[]) if isinstance(payload,dict) else payload


def main():
    now=datetime.now(timezone.utc).replace(microsecond=0)
    registry=load_rows(REGISTRY)
    verified=[r for r in registry if r.get('status')=='VERIFIED' and str(r.get('source','')).upper()=='FOTMOB']
    payload={'schema_version':1,'fast_snapshot_at':now.isoformat(),'source':'FOTMOB','request_count':0,'verified_targets':len(verified),'rows':[],'unmapped_count':0,'health':'NO_VERIFIED_TARGETS'}
    if not verified:
        OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)); print('PHASE3_FAST health=NO_VERIFIED_TARGETS verified_targets=0 requests=0 rows=0'); return 0
    try:
        req=urllib.request.Request(URL.format(date=now.date().isoformat()),headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=12) as response: board=json.load(response)
        payload['request_count']=1
        normalized=normalize_fotmob_board(board,now.isoformat())
        joined,unmapped=join_verified_fast_rows(registry,normalized)
        target_ids={str(r.get('external_id')) for r in verified}
        relevant_unmapped=[r for r in unmapped if str(r.get('external_id')) in target_ids]
        payload.update(rows=joined,unmapped_count=len(relevant_unmapped),board_rows=len(normalized),health='FRESH' if joined else 'TARGETS_NOT_ON_BOARD')
        OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        if joined: LAST_GOOD.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        print(f"PHASE3_FAST health={payload['health']} verified_targets={len(verified)} requests=1 board_rows={len(normalized)} rows={len(joined)} unmapped={len(relevant_unmapped)}")
        for row in joined: print(f"PHASE3_FAST_MATCH event={row['hkjc_event_id']} external={row['external_id']} status={row['status']} minute={row['minute']} score={row['home_score']}-{row['away_score']}")
        return 0
    except Exception as exc:
        payload.update(health='SOURCE_ERROR',error=f'{type(exc).__name__}: {exc}')
        OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        print(f"PHASE3_FAST health=SOURCE_ERROR verified_targets={len(verified)} requests={payload['request_count']} error={type(exc).__name__}")
        return 0

if __name__=='__main__': raise SystemExit(main())
