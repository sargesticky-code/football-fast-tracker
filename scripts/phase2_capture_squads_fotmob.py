"""Phase-2 Layer-2 targeted squad/player capture for CURRENT confirmed FotMob teams only.
No broad crawl. Facts are retained with provider URL/timestamp/raw context; failures fail closed.
"""
from __future__ import annotations
import csv,json,time
from datetime import datetime,timezone
from pathlib import Path
import requests
REG=Path('data/phase2_team_identity_evidence.csv')
FIX=Path('data/phase2_hkjc_current.csv')
OUT=Path('data/phase2_player_master.csv')
HEALTH=Path('data/phase2_squad_health.json')
# Verified current FotMob route is plural /api/data/teams (singular /team returns 404).
BASE='https://www.fotmob.com/api/data/teams'
FIELDS=['hkjc_team_id','hkjc_team_name','provider','provider_team_id','player_id','canonical_name','membership','position','date_of_birth','age','nationality','evidence_class','confirmed','confidence','source_url','source_timestamp','fetched_at','raw_context']
def read(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def active_ids():
 fs=read(FIX);return {r['home_hkjc_id'] for r in fs}|{r['away_hkjc_id'] for r in fs}
def members(payload):
 # FotMob has used both flat and grouped squad shapes; accept only explicit player objects with stable ids.
 sq=payload.get('squad') or payload.get('players') or []
 out=[]
 def walk(x):
  if isinstance(x,list):
   for y in x: walk(y)
  elif isinstance(x,dict):
   if x.get('id') and (x.get('name') or x.get('fullName')): out.append(x)
   for k in ('members','players','items'):
    if k in x: walk(x[k])
 walk(sq);return out
def main():
 active=active_ids(); reg=read(REG); teams={}
 for r in reg:
  if r.get('hkjc_team_id') in active and r.get('external_source')=='fotmob' and r.get('confirmed','').lower()=='true': teams[r['hkjc_team_id']]=r
 now=datetime.now(timezone.utc).isoformat(); rows=[]; failures=[]; covered=0
 for hid,r in sorted(teams.items()):
  tid=r['external_team_id']; url=f'{BASE}?id={tid}'
  try:
   q=requests.get(BASE,params={'id':tid},headers={'User-Agent':'Mozilla/5.0','Accept':'application/json','Referer':'https://www.fotmob.com/'},timeout=20)
   if q.status_code!=200: failures.append({'hkjc_team_id':hid,'team':r['hkjc_name_en'],'class':'SOURCE_ERROR','detail':str(q.status_code)});continue
   p=q.json(); ms=members(p)
   if not ms: failures.append({'hkjc_team_id':hid,'team':r['hkjc_name_en'],'class':'SQUAD_ABSENT','detail':'no explicit squad members'});continue
   covered+=1
   for m in ms:
    dob=m.get('birthDate') or m.get('dateOfBirth') or ''
    rows.append({'hkjc_team_id':hid,'hkjc_team_name':r['hkjc_name_en'],'provider':'fotmob','provider_team_id':tid,'player_id':str(m.get('id')),'canonical_name':m.get('name') or m.get('fullName'),'membership':'CURRENT_SQUAD','position':m.get('position') or m.get('role') or '','date_of_birth':dob,'age':m.get('age') or '','nationality':m.get('country') or m.get('nationality') or '','evidence_class':'FACT','confirmed':'true','confidence':'1.0','source_url':url,'source_timestamp':now,'fetched_at':now,'raw_context':json.dumps({k:m.get(k) for k in ('id','name','position','role','birthDate','dateOfBirth','age','country','nationality') if m.get(k) is not None},ensure_ascii=False,separators=(',',':'))})
   time.sleep(.25)
  except Exception as e: failures.append({'hkjc_team_id':hid,'team':r['hkjc_name_en'],'class':'SOURCE_ERROR','detail':type(e).__name__+': '+str(e)[:120]})
 with OUT.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
 health={'status':'OK' if teams else 'NO_TARGETS','target_confirmed_fotmob_teams':len(teams),'teams_with_squad':covered,'team_coverage_pct':round(100*covered/len(teams),1) if teams else 0,'players':len(rows),'failures':failures,'fetched_at':now}
 HEALTH.write_text(json.dumps(health,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('PHASE2_LAYER2_SQUAD '+json.dumps(health,separators=(',',':')))
if __name__=='__main__':main()
