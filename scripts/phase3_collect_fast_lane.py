#!/usr/bin/env python3
"""Collect a lightweight FotMob heartbeat and join only VERIFIED Layer-2 IDs."""
import json
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from phase3.fast_lane import fast_lane_health, normalize_fotmob_board, join_verified_fast_rows

REGISTRY=ROOT/'data/phase3_live_identity_map.json'
OUT=ROOT/'data/phase3_fast_snapshot.json'
LAST_GOOD=ROOT/'data/phase3_fast_last_good.json'
URL='https://www.fotmob.com/api/data/matches?date={date}'
TERMINAL_STATUSES={'FT','AET','PEN','CANCELLED','POSTPONED','ABANDONED'}


def load_rows(path):
    if not path.exists(): return []
    payload=json.loads(path.read_text())
    return payload.get('rows',[]) if isinstance(payload,dict) else payload


def external_id(row):
    value=row.get('external_id') or row.get('source_match_id')
    return str(value) if value is not None else ''


def fotmob_date(now):
    return now.strftime('%Y%m%d')


def _row_kickoff(row):
    """Read a verified kickoff timestamp without guessing a timezone."""
    for key in ('kickoff_utc','kickoff','start_time','start_time_utc','match_time_utc'):
        value=row.get(key)
        if not isinstance(value,str) or not value.strip():
            continue
        try:
            dt=datetime.fromisoformat(value.strip().replace('Z','+00:00'))
        except ValueError:
            continue
        if dt.tzinfo is None:
            continue
        return dt.astimezone(timezone.utc)
    return None


def board_dates(now, verified):
    """Query today's board plus only adjacent dates supported by verified identities."""
    primary=fotmob_date(now)
    dates=[primary]
    supported=sorted({fotmob_date(dt) for row in verified if (dt:=_row_kickoff(row)) is not None and abs((dt.date()-now.date()).days) <= 1})
    for day in supported:
        if day != primary and day not in dates:
            dates.append(day)
    return dates


def fetch_board(day):
    req=urllib.request.Request(URL.format(date=day),headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=12) as response:
        return json.load(response)


def last_good_meta(now):
    """Return age of the last genuine live heartbeat, purging invalid cache state."""
    if not LAST_GOOD.exists(): return {'last_good_at':None,'last_good_age_seconds':None}
    try:
        old=json.loads(LAST_GOOD.read_text())
        if old.get('health') != 'FRESH_LIVE' or not old.get('live_rows'):
            LAST_GOOD.unlink(missing_ok=True)
            return {'last_good_at':None,'last_good_age_seconds':None}
        stamp=old.get('fast_snapshot_at')
        dt=datetime.fromisoformat(stamp) if stamp else None
        if dt and dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        if not dt or dt > now:
            LAST_GOOD.unlink(missing_ok=True)
            return {'last_good_at':None,'last_good_age_seconds':None}
        age=(now-dt).total_seconds()
        return {'last_good_at':stamp,'last_good_age_seconds':age}
    except Exception:
        LAST_GOOD.unlink(missing_ok=True)
        return {'last_good_at':None,'last_good_age_seconds':None}


def duplicate_observation_ids(rows):
    counts=Counter(str(r.get('external_id') or '') for r in rows if r.get('external_id') is not None)
    return sorted(rid for rid,count in counts.items() if rid and count > 1)


def coverage_meta(target_ids, seen_ids, joined, unmapped):
    """Expose consumer-ready verified mapping coverage without fuzzy rematching."""
    target_ids={str(value) for value in target_ids if str(value)}
    seen_ids={str(value) for value in seen_ids if str(value)}
    unmapped_ids=sorted({str(r.get('external_id')) for r in unmapped if r.get('external_id') is not None and str(r.get('external_id')) in target_ids})
    return {
        'mapped_rows': len(joined),
        'unmapped_count': len(unmapped_ids),
        'unmapped_external_ids': unmapped_ids,
        'missing_target_ids': sorted(target_ids-seen_ids),
    }


def main():
    now=datetime.now(timezone.utc).replace(microsecond=0)
    registry=load_rows(REGISTRY)
    verified=[r for r in registry if r.get('status')=='VERIFIED' and str(r.get('source','')).upper()=='FOTMOB' and external_id(r)]
    payload={'schema_version':1,'fast_snapshot_at':now.isoformat(),'source':'FOTMOB','request_count':0,'primary_board_requests':0,'fallback_board_requests':0,'fallback_trigger_target_ids':[],'fallback_recovered_target_ids':[],'duplicate_observation_ids':[],'request_failures':0,'verified_targets':len(verified),'rows':[],'mapped_rows':0,'live_rows':0,'terminal_rows':0,'unmapped_count':0,'unmapped_external_ids':[],'missing_target_ids':[],'health':'NO_VERIFIED_TARGETS',**last_good_meta(now)}
    if not verified:
        OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)); print('PHASE3_FAST health=NO_VERIFIED_TARGETS verified_targets=0 requests=0 failures=0 rows=0 live_rows=0'); return 0
    try:
        target_ids={external_id(r) for r in verified}
        normalized=[]
        seen_ids=set()
        dates_tried=[]
        for board_index,day in enumerate(board_dates(now,verified)):
            if board_index > 0 and not payload['fallback_trigger_target_ids']:
                payload['fallback_trigger_target_ids']=sorted(target_ids-seen_ids)
            before_ids=set(seen_ids)
            payload['request_count']+=1
            if board_index == 0: payload['primary_board_requests']+=1
            else: payload['fallback_board_requests']+=1
            dates_tried.append(day)
            board=fetch_board(day)
            for row in normalize_fotmob_board(board,now.isoformat()):
                rid=str(row.get('external_id') or '')
                normalized.append(row)
                if rid: seen_ids.add(rid)
            if board_index > 0:
                recovered=(seen_ids-before_ids) & set(payload['fallback_trigger_target_ids'])
                payload['fallback_recovered_target_ids']=sorted(set(payload['fallback_recovered_target_ids']) | recovered)
            if target_ids.issubset(seen_ids): break
        joined,unmapped=join_verified_fast_rows(registry,normalized)
        coverage=coverage_meta(target_ids,seen_ids,joined,unmapped)
        freshness=fast_lane_health(joined,now.isoformat(),now=now.isoformat(),request_failures=0)
        live_rows=freshness['live_rows']
        terminal_rows=sum(1 for row in joined if str(row.get('status') or '').strip().upper() in TERMINAL_STATUSES)
        health=freshness['health'] if joined else 'TARGETS_NOT_ON_BOARD'
        payload.update(rows=joined,live_rows=live_rows,terminal_rows=terminal_rows,board_rows=len(normalized),board_dates=dates_tried,duplicate_observation_ids=duplicate_observation_ids(normalized),health=health,snapshot_age_seconds=freshness['snapshot_age_seconds'],**coverage)
        if health == 'FRESH_LIVE' and live_rows:
            payload.update(last_good_at=now.isoformat(),last_good_age_seconds=0)
            LAST_GOOD.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        print(f"PHASE3_FAST health={health} verified_targets={len(verified)} requests={payload['request_count']} primary_requests={payload['primary_board_requests']} fallback_requests={payload['fallback_board_requests']} failures=0 board_rows={len(normalized)} mapped_rows={payload['mapped_rows']} live_rows={live_rows} terminal_rows={terminal_rows} unmapped={payload['unmapped_count']} missing_targets={len(payload['missing_target_ids'])} fallback_recovered={len(payload['fallback_recovered_target_ids'])} duplicate_ids={len(payload['duplicate_observation_ids'])} snapshot_age={payload['snapshot_age_seconds']} last_good_age={payload['last_good_age_seconds']}")
        for row in joined: print(f"PHASE3_FAST_MATCH event={row['hkjc_event_id']} external={row['external_id']} status={row['status']} minute={row['minute']} score={row['home_score']}-{row['away_score']}")
        return 0
    except Exception as exc:
        payload.update(health='SOURCE_ERROR',request_failures=1,error=f'{type(exc).__name__}: {exc}')
        OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        print(f"PHASE3_FAST health=SOURCE_ERROR verified_targets={len(verified)} requests={payload['request_count']} failures=1 last_good_age={payload['last_good_age_seconds']} error={type(exc).__name__}")
        return 0

if __name__=='__main__': raise SystemExit(main())