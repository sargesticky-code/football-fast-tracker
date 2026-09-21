"""Targeted Phase-2 Sofascore resolver with auditable fail-closed diagnostics."""
from __future__ import annotations
import argparse,csv,json,re,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from difflib import SequenceMatcher
try:
 from curl_cffi import requests
except ImportError:
 import requests
HKT=timezone(timedelta(hours=8)); BASE="https://www.sofascore.com/api/v1"
FIELDS=["hkjc_team_id","hkjc_name_en","hkjc_name_ch","cohort","external_source","external_team_id","external_name","evidence_class","confirmed","confidence","source_url","source_timestamp","fetched_at","raw_context"]
DIAG=["hkjc_team_id","hkjc_name_en","cohort","hkjc_event_id","reason","candidate_count","best_score","best_external_name","best_external_team_id","kickoff_delta_seconds","fetched_at"]
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
def get(url):
 try:return requests.get(url,timeout=15,impersonate="chrome").json()
 except TypeError:return requests.get(url,timeout=15,headers={"User-Agent":"Mozilla/5.0"}).json()
def write_diag(path,ds):
 Path(path).parent.mkdir(parents=True,exist_ok=True)
 with open(path,"w",encoding="utf-8-sig",newline="") as f:
  w=csv.DictWriter(f,fieldnames=DIAG);w.writeheader();w.writerows(ds)
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--fixtures",default="data/phase2_hkjc_current.csv");ap.add_argument("--registry",default="data/phase2_team_identity_evidence.csv");ap.add_argument("--diagnostics",default="data/phase2_identity_resolution_diagnostics.csv");a=ap.parse_args()
 fs=rows(a.fixtures);reg=rows(a.registry);known={(x["hkjc_team_id"],x["external_source"]):x for x in reg if str(x.get("confirmed","")).lower() in ("true","1","yes")}
 added=[];attempted=set();diags=[];events=[];source_errors=[];now=datetime.now(timezone.utc).isoformat()
 dates=sorted({datetime.fromisoformat(f["kickoff_hkt"]).date().isoformat() for f in fs})
 for d in dates:
  url=f"{BASE}/sport/football/scheduled-events/{d}"
  try:events+=get(url).get("events",[]);time.sleep(.5)
  except Exception as e:source_errors.append((d,type(e).__name__))
 for f in fs:
  kick=datetime.fromisoformat(f["kickoff_hkt"])
  for side,other in (("home","away"),("away","home")):
   hid=f[f"{side}_hkjc_id"]
   if (hid,"sofascore") in known or hid in attempted:continue
   attempted.add(hid);hn=f[f"{side}_en"];on=f[f"{other}_en"];hc=cohort(hn);near=[];cohort_ok=[];name_ok=[]
   for e in events:
    try:
     ek=datetime.fromtimestamp(e["startTimestamp"],timezone.utc).astimezone(HKT);delta=abs((ek-kick).total_seconds())
     if delta>1800:continue
     et=e[side+"Team"];ot=e[other+"Team"];s1=sim(hn,et.get("name",""));s2=sim(on,ot.get("name",""));item=(round((s1+s2)/2,3),e,et,ek,delta)
     near.append(item)
     if cohort(et.get("name",""))==hc:cohort_ok.append(item)
     if cohort(et.get("name",""))==hc and s1>=.62 and s2>=.62:name_ok.append(item)
    except Exception:pass
   name_ok.sort(key=lambda x:x[0],reverse=True)
   if len(name_ok)==1 and name_ok[0][0]>=.72:
    score,e,et,ek,delta=name_ok[0];added.append({"hkjc_team_id":hid,"hkjc_name_en":hn,"hkjc_name_ch":f.get(f"{side}_ch",""),"cohort":hc,"external_source":"sofascore","external_team_id":str(et["id"]),"external_name":et.get("name",""),"evidence_class":"CONFIRMED_FACT","confirmed":"true","confidence":str(score),"source_url":f"{BASE}/sport/football/scheduled-events/{ek.date().isoformat()}","source_timestamp":ek.isoformat(),"fetched_at":now,"raw_context":json.dumps({"hkjc_event_id":f["hkjc_event_id"],"sofascore_event_id":e.get("id"),"kickoff_delta_seconds":delta},separators=(",",":"))});continue
   reason="SOURCE_ERROR" if source_errors and not events else "NO_EVENT_WITHIN_30M" if not near else "COHORT_MISMATCH" if not cohort_ok else "NAME_MISMATCH" if not name_ok else "AMBIGUOUS_CANDIDATES" if len(name_ok)>1 else "LOW_CONFIDENCE"
   best=(name_ok or cohort_ok or near);best=sorted(best,key=lambda x:x[0],reverse=True)[0] if best else None
   diags.append({"hkjc_team_id":hid,"hkjc_name_en":hn,"cohort":hc,"hkjc_event_id":f["hkjc_event_id"],"reason":reason,"candidate_count":len(name_ok),"best_score":best[0] if best else "","best_external_name":best[2].get("name","") if best else "","best_external_team_id":best[2].get("id","") if best else "","kickoff_delta_seconds":best[4] if best else "","fetched_at":now})
 if added:
  with open(a.registry,"a",encoding="utf-8-sig",newline="") as out:csv.DictWriter(out,fieldnames=FIELDS).writerows(added)
 write_diag(a.diagnostics,diags)
 counts={};
 for d in diags:counts[d["reason"]]=counts.get(d["reason"],0)+1
 print("PHASE2_SOFASCORE "+json.dumps({"attempted":len(attempted),"confirmed_new":len(added),"unresolved":len(diags),"failure_classes":counts,"source_errors":source_errors},separators=(",",":")))
if __name__=="__main__":main()
