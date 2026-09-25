#!/usr/bin/env python3
"""Build fail-closed Phase-2 Layer-6 rotation/rest/congestion/depth evidence.

Uses only Phase-2 generated HKJC fixtures and verified current squad master.
No external/API calls. Rotation/rest remain unavailable until verified historical XI exists.
"""
import csv, json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DATA=Path('data')
FIX=DATA/'phase2_hkjc_current.csv'
PLAYERS=DATA/'phase2_player_master.csv'
OUT=DATA/'phase2_rotation_context.csv'
HEALTH=DATA/'phase2_rotation_health.json'

def dt(s): return datetime.fromisoformat(s.replace('Z','+00:00'))

def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))

fixtures=rows(FIX)
players=rows(PLAYERS) if PLAYERS.exists() else []
by_team=defaultdict(list)
for r in players:
    if str(r.get('confirmed','')).lower()=='true' and r.get('membership')=='CURRENT_SQUAD':
        by_team[r['hkjc_team_id']].append(r)

team_fixtures=defaultdict(list)
for f in fixtures:
    ko=dt(f['kickoff_hkt'])
    for side in ('home','away'):
        tid=f[f'{side}_hkjc_id']; team_fixtures[tid].append((ko,f['hkjc_event_id']))

out=[]
for f in fixtures:
    ko=dt(f['kickoff_hkt'])
    for side in ('home','away'):
        tid=f[f'{side}_hkjc_id']; name=f[f'{side}_en']; squad=by_team.get(tid,[])
        pos=Counter((p.get('position') or 'Unknown') for p in squad)
        near=team_fixtures.get(tid,[])
        # Current fixture universe supports forward congestion only; never infer past rest.
        future7=sum(1 for k,_ in near if ko < k <= ko+timedelta(days=7))
        future14=sum(1 for k,_ in near if ko < k <= ko+timedelta(days=14))
        out.append({
            'hkjc_event_id':f['hkjc_event_id'],'kickoff_hkt':f['kickoff_hkt'],
            'hkjc_team_id':tid,'hkjc_team_name':name,'side':side.upper(),
            'verified_history_matches':0,'previous_verified_kickoff':'','rest_hours':'',
            'starter_overlap':'','starters_changed':'',
            'verified_squad_size':len(squad),'goalkeepers':pos.get('Goalkeeper',0),
            'defenders':pos.get('Defender',0),'midfielders':pos.get('Midfielder',0),
            'attackers':pos.get('Attacker',0),'future_fixtures_7d':future7,'future_fixtures_14d':future14,
            'rotation_evidence_class':'INSUFFICIENT_HISTORY',
            'depth_evidence_class':'FACT' if squad else 'NO_VERIFIED_SQUAD',
            'congestion_evidence_class':'FACT_CURRENT_HKJC_UNIVERSE',
            'source':'phase2_hkjc_current+phase2_player_master'
        })
fields=list(out[0]) if out else []
with OUT.open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(out)
health={
 'layer':6,'generated_at':datetime.now().astimezone().isoformat(),
 'fixtures':len(fixtures),'team_sides':len(out),'unique_teams':len({r['hkjc_team_id'] for r in out}),
 'depth_fact_sides':sum(r['depth_evidence_class']=='FACT' for r in out),
 'rotation_verified_sides':sum(r['verified_history_matches']>0 for r in out),
 'rotation_insufficient_history_sides':sum(r['rotation_evidence_class']=='INSUFFICIENT_HISTORY' for r in out),
 'layer6_exit':False,
 'next_objective':'ADD_VERIFIED_HISTORICAL_XI_OR_FIXTURE_HISTORY_FOR_ROTATION_AND_REST',
 'guardrail':'Current fixture universe is used only for forward congestion; no past rest/rotation is inferred.'
}
HEALTH.write_text(json.dumps(health,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(health,ensure_ascii=False))
