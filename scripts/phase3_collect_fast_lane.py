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
# Keep the fast lane on the same proven one-board transport used by Layer 2.
URL='https://www.fotmob.com/api/data/matches?date={date}'


def load_rows(path):
    if not path.exists(): return []
    payload=json.loads(path.read_text())
    return payload.get('rows',[]) if isinstance(payload,dict) else payload


def external_id(row):
    """Use the persistent Layer-2 ID without attempting any fuzzy rematch."""
    value=row.get('external_id') or row.get('source_match_id')
    return str(value) if value is not None else ''


def last_good_meta(now):
    if not LAST_GOOD.exists(): return {'last_good_at':None,'last_good_age_seconds':None}
    try:
        old=json.loads(LAST_GOOD.read_text())
        stamp=old.get('fast_snapshot_at')
        dt=datetime.fromisoformat(stamp) if stamp else None
        age=max(0,(now-dt).total_seconds()) if dt else None
        return {'last_good_at':stamp,'last_good_age_seconds':age}
    except Exception:
        return {'last_good_at':None,'last_good_age_seconds':None}


def main():
    now=datetime.now(timezone.utc).replace(microsecond=0)
    registry=load_rows(REGISTRY)
    verified=[r for r in registry if r.get('status')=='VERIFIED' and str(r.get('source','')).upper()=='FOTMOB' and external_id(r)]
    payload={'schema_version':1,'fast_snapshot_at':now.isoformat(),'source':'FOTMOB','request_count':0,'request_failures':0,'verified_targets':len(verified),'rows':[],'unmapped_count':0,'health':'NO_VERIFIED_TARGETS',**last_good_meta(now)}
    if not verified:
        OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)); print('PHASE3_FAST health=NO_VERIFIED_TARGETS verified_targets=0 requests=0 failures=0 rows=0'); return 0
    try:
        req=urllib.request.Request(URL.format(date=now.date().isoformat()),headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
        payload['request_count']=1
        with urllib.request.urlopen(req,timeout=12) as response: board=json.load(response)
        normalized=normalize_fotmob_board(board,now.isoformat())
        joined,unmapped=join_verified_fast_rows(registry,normalized)
        target_ids={external_id(r) for r in verified}
        relevant_unmapped=[r for r in unmapped if str(r.get('external_id') or '') in target_ids]
        board_ids={str(r.get('external_id') or '') for r in normalized}
        missing_target_ids=sorted(target_ids-board_ids)
        payload.update(rows=joined,unmapped_count=len(relevant_unmapped),missing_target_ids=missing_target_ids,board_rows=len(normalized),health='FRESH' if joined else 'TARGETS_NOT_ON_BOARD')
        if joined:
            payload.update(last_good_at=now.isoformat(),last_good_age_seconds=0)
            LAST_GOOD.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        print(f"PHASE3_FAST health={payload['health']} verified_targets={len(verified)} requests=1 failures=0 board_rows={len(normalized)} rows={len(joined)} unmapped={len(relevant_unmapped)} missing_targets={len(missing_target_ids)} last_good_age={payload['last_good_age_seconds']}")
        for row in joined: print(f"PHASE3_FAST_MATCH event={row['hkjc_event_id']} external={row['external_id']} status={row['status']} minute={row['minute']} score={row['home_score']}-{row['away_score']}")
        return 0
    except Exception as exc:
        payload.update(health='SOURCE_ERROR',request_failures=1,error=f'{type(exc).__name__}: {exc}')
        OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        print(f"PHASE3_FAST health=SOURCE_ERROR verified_targets={len(verified)} requests={payload['request_count']} failures=1 last_good_age={payload['last_good_age_seconds']} error={type(exc).__name__}")
        return 0

if __name__=='__main__': raise SystemExit(main())
