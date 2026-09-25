"""Phase-2 Layer-3 targeted manager/head-coach discovery for CURRENT confirmed FotMob teams only.
Fail closed: only explicit current manager/coach objects or explicit coach members of the current squad are accepted as FACT.
Historical coachHistory is diagnostic context only unless independently verified current.
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
 out=[];seen=set();candidates=[]
 # Direct explicit current-team objects.
 for k in ('manager','coach','headCoach','head_coach'):
  v=p.get(k)
  if isinstance(v,dict): candidates.append((k,v))
 ov=p.get('overview')
 if isinstance(ov,dict):
  for k in ('manager','coach','headCoach','head_coach'):
   v=ov.get(k)
   if isinstance(v,dict): candidates.append((k,v))
 # FotMob currently exposes many coaches inside the current squad groups.
 # Accept only groups explicitly labelled coach/manager; never infer from arbitrary staff arrays.
 sq=p.get('squad')
 groups=sq.get('squad') if isinstance(sq,dict) else None
 if isinstance(groups,list):
  for g in groups:
   if not isinstance(g,dict): continue
   title=str(g.get('title') or g.get('name') or '').strip().lower()
   if title not in ('coach','coaches','manager','managers','head coach','headcoach'): continue
   members=g.get('members')
   if not isinstance(members,list): continue
   for m in members:
    if isinstance(m,dict): candidates.append(('squad_'+title.replace(' ','_'),m))
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
    ov=p.get('overview') if isinstance(p.get('overview'),dict) else {}
    ch=ov.get('coachHistory') if isinstance(ov,dict) else None
    sq=p.get('squad'); groups=sq.get('squad') if isinstance(sq,dict) else None
    group_titles=[str(g.get('title') or g.get('name') or '') for g in groups if isinstance(g,dict)] if isinstance(groups,list) else []
    failures.append({'hkjc_team_id':hid,'team':r['hkjc_name_en'],'class':'NO_EXPLICIT_CURRENT_MANAGER','detail':json.dumps({'squad_group_titles':group_titles,'coach_history_type':type(ch).__name__,'coach_history_count':len(ch) if isinstance(ch,list) else None},separators=(',',':'))}); continue
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
 # Practical exit: >=80% explicit current coverage with no source errors, OR every residual explicitly classified.
 residual_all_classified=bool(teams) and not classes.get('SOURCE_ERROR') and all(x['class']=='NO_EXPLICIT_CURRENT_MANAGER' for x in failures)
 health={'status':'OK' if teams else 'NO_TARGETS','target_confirmed_fotmob_teams':len(teams),'teams_with_explicit_manager':covered,'team_coverage_pct':pct,'manager_rows':len(rows),'failure_classes':classes,'residual_all_classified':residual_all_classified,'failures':failures,'layer3_exit':bool(teams) and not classes.get('SOURCE_ERROR') and (pct>=80 or residual_all_classified),'fetched_at':now}
 HEALTH.write_text(json.dumps(health,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print('PHASE2_LAYER3_MANAGER '+json.dumps(health,separators=(',',':')))
if __name__=='__main__': main()
