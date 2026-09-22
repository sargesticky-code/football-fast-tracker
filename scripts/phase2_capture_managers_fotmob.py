"""Phase-2 Layer-3 targeted manager/head-coach discovery for CURRENT confirmed FotMob teams only.
Fail closed: only explicit manager/coach objects in the current team payload are accepted as FACT.
"""
from __future__ import annotations
import csv,json,time
from datetime import datetime,timezone
from pathlib import Path
import requests
REG=Path('data/phase2_team_identity_evidence.csv'); FIX=Path('data/phase2_hkjc_current.csv')
OUT=Path('data/phase2_manager_master.csv'); HEALTH=Path('data/phase2_manager_health.json')
BASE='https://www.fotmob.com/api/data/teams'
FIELDS=['hkjc_team_id','hkjc_team_name','provider','provider_team_id','manager_id','canonical_name','role','appointment_date','tenure_days','evidence_class','confirmed','confidence','source_url','source_timestamp','fetched_at','raw_context']
def read(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def active_ids():
 fs=read(FIX);return {r['home_hkjc_id'] for r in fs}|{r['away_hkjc_id'] for r in fs}
def explicit_managers(p):
 out=[];seen=set()
 # Deliberately narrow. Do not infer a coach from arbitrary people/staff arrays.
 candidates=[]
 for k in ('manager','coach','headCoach','head_coach'):
  v=p.get(k)
  if isinstance(v,dict): candidates.append((k,v))
 ov=p.get('overview')
 if isinstance(ov,dict):
  for k in ('manager','coach','headCoach','head_coach'):
   v=ov.get(k)
   if isinstance(v,dict): candidates.append((k,v))
 for key,m in candidates:
  name=m.get('name') or m.get('fullName')
  if not name: continue
  mid=str(m.get('id') or m.get('managerId') or m.get('coachId') or '')
  sig=(mid,name)
  if sig in seen: continue
  seen.add(sig);out.append((key,m))
 return out
def main():
 active=active_ids(); teams={}
 for r in read(REG):
  if r.get('hkjc_team_id') in active and r.get('external_source')=='fotmob' and r.get('confirmed','').lower()=='true': teams[r['hkjc_team_id']]=r
 now=datetime.now(timezone.utc).isoformat(); rows=[]; failures=[]; covered=0
 for hid,r in sorted(teams.items()):
  tid=r['external_team_id']; url=f'{BASE}?id={tid}'
  try:
   q=requests.get(BASE,params={'id':tid},headers={'User-Agent':'Mozilla/5.0','Accept':'application/json','Referer':'https://www.fotmob.com/'},timeout=20)
   if q.status_code!=200: failures.append({'hkjc_team_id':hid,'team':r['hkjc_name_en'],'class':'SOURCE_ERROR','detail':str(q.status_code)}); continue
   p=q.json(); ms=explicit_managers(p)
   if not ms:
    failures.append({'hkjc_team_id':hid,'team':r['hkjc_name_en'],'class':'NO_EXPLICIT_MANAGER','detail':json.dumps({'top_keys':sorted(p.keys()),'overview_keys':sorted((p.get('overview') or {}).keys()) if isinstance(p.get('overview'),dict) else []},separators=(',',':'))}); continue
   covered+=1
   for role,m in ms:
    ap=m.get('appointmentDate') or m.get('appointed') or m.get('startDate') or ''
    rows.append({'hkjc_team_id':hid,'hkjc_team_name':r['hkjc_name_en'],'provider':'fotmob','provider_team_id':tid,'manager_id':str(m.get('id') or m.get('managerId') or m.get('coachId') or ''),'canonical_name':m.get('name') or m.get('fullName'),'role':role,'appointment_date':ap,'tenure_days':'','evidence_class':'FACT','confirmed':'true','confidence':'1.0','source_url':url,'source_timestamp':now,'fetched_at':now,'raw_context':json.dumps(m,ensure_ascii=False,separators=(',',':'))})
   time.sleep(.2)
  except Exception as e: failures.append({'hkjc_team_id':hid,'team':r['hkjc_name_en'],'class':'SOURCE_ERROR','detail':type(e).__name__+': '+str(e)[:120]})
 with OUT.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
 pct=round(100*covered/len(teams),1) if teams else 0; classes={}
 for x in failures: classes[x['class']]=classes.get(x['class'],0)+1
 health={'status':'OK' if teams else 'NO_TARGETS','target_confirmed_fotmob_teams':len(teams),'teams_with_explicit_manager':covered,'team_coverage_pct':pct,'manager_rows':len(rows),'failure_classes':classes,'failures':failures,'layer3_exit':pct>=80 and not classes.get('SOURCE_ERROR'),'fetched_at':now}
 HEALTH.write_text(json.dumps(health,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print('PHASE2_LAYER3_MANAGER '+json.dumps(health,separators=(',',':')))
if __name__=='__main__': main()
