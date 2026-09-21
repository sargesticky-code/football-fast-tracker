"""Targeted Phase-2 identity fallback using TheSportsDB public event-day endpoint.
Only current HKJC fixture dates are requested. Confirmation remains fixture-level,
both-team compatible, cohort compatible, and kickoff within +/-30 minutes.
"""
from __future__ import annotations
import argparse,csv,json,re,time
from datetime import datetime,timedelta,timezone
from difflib import SequenceMatcher
from pathlib import Path
import requests
HKT=timezone(timedelta(hours=8)); BASE="https://www.thesportsdb.com/api/v1/json/123/eventsday.php"; SEARCH="https://www.thesportsdb.com/api/v1/json/123/searchevents.php"
FIELDS=["hkjc_team_id","hkjc_name_en","hkjc_name_ch","cohort","external_source","external_team_id","external_name","evidence_class","confirmed","confidence","source_url","source_timestamp","fetched_at","raw_context"]
def rows(p):
 if not Path(p).exists(): return []
 with open(p,encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def norm(s):return re.sub(r"[^a-z0-9]+","",str(s).lower())
def sim(a,b):return SequenceMatcher(None,norm(a),norm(b)).ratio()
def cohort(name):
 s=str(name).upper()
 for x in ("WOMEN","U17","U18","U19","U20","U21","U23","RESERVE"):
  if x in s:return x
 return "SENIOR"
def event_dt(e):
 d=e.get("dateEvent"); t=e.get("strTime") or "00:00:00"
 if not d:return None
 try:return datetime.fromisoformat(f"{d}T{t.replace('Z','')}").replace(tzinfo=timezone.utc).astimezone(HKT)
 except Exception:return None
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--fixtures",default="data/phase2_hkjc_current.csv");ap.add_argument("--registry",default="data/phase2_team_identity_evidence.csv");a=ap.parse_args()
 fs=rows(a.fixtures);reg=rows(a.registry);known={(x.get("hkjc_team_id"),x.get("external_source")) for x in reg if str(x.get("confirmed","")).lower() in ("true","1","yes")}
 dates=sorted({datetime.fromisoformat(f["kickoff_hkt"]).date().isoformat() for f in fs}); events=[]; errors=[]; counts={}; now=datetime.now(timezone.utc).isoformat()
 for d in dates:
  url=f"{BASE}?d={d}&s=Soccer"
  try:
   r=requests.get(url,timeout=15,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"});r.raise_for_status();batch=r.json().get("events") or [];counts[d]=len(batch);events+=batch;time.sleep(.5)
  except Exception as e:errors.append([d,type(e).__name__,getattr(getattr(e,"response",None),"status_code",None)])
 added=[];attempted=set();fail={};search_requests=0
 for f in fs:
  kick=datetime.fromisoformat(f["kickoff_hkt"])
  for side,other in (("home","away"),("away","home")):
   hid=f[f"{side}_hkjc_id"]
   if (hid,"thesportsdb") in known or hid in attempted:continue
   attempted.add(hid); hn=f[f"{side}_en"]; on=f[f"{other}_en"]; hc=cohort(hn); cand=[]
   for e in events:
    ek=event_dt(e)
    if not ek or abs((ek-kick).total_seconds())>1800:continue
    en=e.get("strHomeTeam" if side=="home" else "strAwayTeam",""); eo=e.get("strAwayTeam" if side=="home" else "strHomeTeam","")
    s1,s2=sim(hn,en),sim(on,eo)
    if cohort(en)==hc and s1>=.62 and s2>=.62:cand.append((round((s1+s2)/2,3),e,en,ek))
   cand.sort(key=lambda x:x[0],reverse=True)
   if len(cand)==1 and cand[0][0]>=.72:
    score,e,en,ek=cand[0]; ext=e.get("idHomeTeam" if side=="home" else "idAwayTeam")
    if ext:
     added.append({"hkjc_team_id":hid,"hkjc_name_en":hn,"hkjc_name_ch":f.get(f"{side}_ch",""),"cohort":hc,"external_source":"thesportsdb","external_team_id":str(ext),"external_name":en,"evidence_class":"CONFIRMED_FACT","confirmed":"true","confidence":str(score),"source_url":f"{BASE}?d={ek.date().isoformat()}&s=Soccer","source_timestamp":ek.isoformat(),"fetched_at":now,"raw_context":json.dumps({"hkjc_event_id":f["hkjc_event_id"],"thesportsdb_event_id":e.get("idEvent")},separators=(",",":"))});continue
   reason="SOURCE_ERROR" if errors and not events else "NO_EVENT_WITHIN_30M_OR_NAME_MATCH" if not cand else "AMBIGUOUS_CANDIDATES"
   fail[reason]=fail.get(reason,0)+1
 if added:
  exists=Path(a.registry).exists() and Path(a.registry).stat().st_size>0
  with open(a.registry,"a",encoding="utf-8-sig",newline="") as out:
   w=csv.DictWriter(out,fieldnames=FIELDS)
   if not exists:w.writeheader()
   w.writerows(added)
 print("PHASE2_THESPORTSDB "+json.dumps({"attempted":len(attempted),"confirmed_new":len(added),"unresolved":len(attempted)-len(added),"failure_classes":fail,"source_errors":errors,"source_event_counts":counts,"total_source_events":len(events),"targeted_search_requests":search_requests},separators=(",",":")))
if __name__=="__main__":main()
