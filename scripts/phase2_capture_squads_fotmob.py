"""Phase-2 Layer-2 targeted squad/player capture for CURRENT confirmed FotMob teams only.
No broad crawl. Facts are retained with provider URL/timestamp/raw context; failures fail closed.
"""
from __future__ import annotations
import csv,json,time
from datetime import datetime,timezone
from pathlib import Path
import requests
REG=Path('data/phase2_team_identity_evidence.csv'); FIX=Path('data/phase2_hkjc_current.csv')
OUT=Path('data/phase2_player_master.csv'); HEALTH=Path('data/phase2_squad_health.json')
BASE='https://www.fotmob.com/api/data/teams'
FIELDS=['hkjc_team_id','hkjc_team_name','provider','provider_team_id','player_id','canonical_name','membership','position','date_of_birth','age','nationality','evidence_class','confirmed','confidence','source_url','source_timestamp','fetched_at','raw_context']
def read(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def active_ids():
 fs=read(FIX);return {r['home_hkjc_id'] for r in fs}|{r['away_hkjc_id'] for r in fs}
def members(payload):
 out=[];seen=set()
 def add(m,group=''):
  if not isinstance(m,dict) or not m.get('id') or not (m.get('name') or m.get('fullName')):return
  pid=str(m['id'])
  if pid in seen:return
  seen.add(pid);x=dict(m);x['_position_group']=group;out.append(x)
 sq=payload.get('squad')
 if isinstance(sq,dict):
  groups=sq.get('squad') or []
  if isinstance(groups,list):
   for g in groups:
    if not isinstance(g,dict):continue
    for m in g.get('members') or []:add(m,g.get('title') or '')
 if not out:
  root=payload.get('players') or sq or []
  def walk(x,group=''):
   if isinstance(x,list):
    for y in x:walk(y,group)
   elif isinstance(x,dict):
    add(x,group);ng=x.get('title') or group
    for k in ('members','players','items','squad'):
     if k in x:walk(x[k],ng)
  walk(root)
 return out
def main():
 active=active_ids();reg=read(REG);teams={}
 for r in reg:
  if r.get('hkjc_team_id') in active and r.get('external_source')=='fotmob' and r.get('confirmed','').lower()=='true':teams[r['hkjc_team_id']]=r
 now=datetime.now(timezone.utc).isoformat();rows=[];failures=[];covered=0
 for hid,r in sorted(teams.items()):
  tid=r['external_team_id'];url=f'{BASE}?id={tid}'
  try:
   q=requests.get(BASE,params={'id':tid},headers={'User-Agent':'Mozilla/5.0','Accept':'application/json','Referer':'https://www.fotmob.com/'},timeout=20)
   if q.status_code!=200:failures.append({'hkjc_team_id':hid,'team':r['hkjc_name_en'],'class':'SOURCE_ERROR','detail':str(q.status_code)});continue
   p=q.json();ms=members(p)
   if not ms:
    sq=p.get('squad');groups=sq.get('squad') if isinstance(sq,dict) else None
    group_count=len(groups) if isinstance(groups,list) else 0
    member_count=sum(len(g.get('members') or []) for g in groups if isinstance(g,dict)) if isinstance(groups,list) else 0
    klass='PROVIDER_ROSTER_EMPTY' if isinstance(sq,dict) and isinstance(groups,list) and member_count==0 else 'SCHEMA_UNRESOLVED'
    failures.append({'hkjc_team_id':hid,'team':r['hkjc_name_en'],'class':klass,'detail':json.dumps({'squad_keys':sorted(sq.keys()) if isinstance(sq,dict) else [],'group_count':group_count,'member_count':member_count},separators=(',',':'))});continue
   covered+=1
   for m in ms:
    dob=m.get('birthDate') or m.get('dateOfBirth') or '';role=m.get('position') or m.get('role') or m.get('_position_group') or ''
    if isinstance(role,dict):role=role.get('fallback') or role.get('label') or role.get('key') or ''
    nat=m.get('country') or m.get('nationality') or m.get('cname') or m.get('ccode') or ''
    rows.append({'hkjc_team_id':hid,'hkjc_team_name':r['hkjc_name_en'],'provider':'fotmob','provider_team_id':tid,'player_id':str(m.get('id')),'canonical_name':m.get('name') or m.get('fullName'),'membership':'CURRENT_SQUAD','position':role,'date_of_birth':dob,'age':m.get('age') or '','nationality':nat,'evidence_class':'FACT','confirmed':'true','confidence':'1.0','source_url':url,'source_timestamp':now,'fetched_at':now,'raw_context':json.dumps({k:m.get(k) for k in ('id','name','firstName','lastName','role','position','dateOfBirth','birthDate','age','cname','ccode','country','nationality','shirtNumber') if m.get(k) is not None},ensure_ascii=False,separators=(',',':'))})
   time.sleep(.25)
  except Exception as e:failures.append({'hkjc_team_id':hid,'team':r['hkjc_name_en'],'class':'SOURCE_ERROR','detail':type(e).__name__+': '+str(e)[:120]})
 with OUT.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
 n=len(rows);pos=sum(bool(x['position']) for x in rows);dob=sum(bool(x['date_of_birth']) for x in rows);age=sum(bool(x['age']) for x in rows);nat=sum(bool(x['nationality']) for x in rows)
 pct=round(100*covered/len(teams),1) if teams else 0; classes={}
 for x in failures:classes[x['class']]=classes.get(x['class'],0)+1
 residual_all_classified=bool(failures) and not any(x['class'] in ('SOURCE_ERROR','SCHEMA_UNRESOLVED') for x in failures)
 layer2_exit=(pct>=90.0 or residual_all_classified) and n>0 and (100*pos/n if n else 0)>=95 and (100*nat/n if n else 0)>=95
 health={'status':'OK' if teams else 'NO_TARGETS','target_confirmed_fotmob_teams':len(teams),'teams_with_squad':covered,'team_coverage_pct':pct,'players':n,'position_coverage_pct':round(100*pos/n,1) if n else 0,'dob_coverage_pct':round(100*dob/n,1) if n else 0,'age_coverage_pct':round(100*age/n,1) if n else 0,'nationality_coverage_pct':round(100*nat/n,1) if n else 0,'failure_classes':classes,'residual_all_classified':residual_all_classified,'layer2_exit':layer2_exit,'failures':failures,'fetched_at':now}
 HEALTH.write_text(json.dumps(health,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print('PHASE2_LAYER2_SQUAD '+json.dumps(health,separators=(',',':')))
if __name__=='__main__':main()
