"""Targeted Phase-2 Sofascore resolver. Fail closed: fixture context required."""
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
def rows(p):
 if not Path(p).exists(): return []
 with open(p,encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def norm(s): return re.sub(r"[^a-z0-9]+","",str(s).lower())
def sim(a,b): return SequenceMatcher(None,norm(a),norm(b)).ratio()
def cohort(name):
 s=str(name).upper()
 for x in ("WOMEN","U17","U18","U19","U20","U21","U23","RESERVE"):
  if x in s:return x
 return "SENIOR"
def get(url):
 try:return requests.get(url,timeout=15,impersonate="chrome").json()
 except TypeError:return requests.get(url,timeout=15,headers={"User-Agent":"Mozilla/5.0"}).json()
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--fixtures",default="data/phase2_hkjc_current.csv");ap.add_argument("--registry",default="data/phase2_team_identity_evidence.csv");a=ap.parse_args()
 fs=rows(a.fixtures); reg=rows(a.registry); known={(x["hkjc_team_id"],x["external_source"]):x for x in reg if str(x.get("confirmed","")).lower() in ("true","1","yes")}
 added=[]; attempted=set()
 dates=sorted({datetime.fromisoformat(f["kickoff_hkt"]).date().isoformat() for f in fs})
 events=[]
 for d in dates:
  url=f"{BASE}/sport/football/scheduled-events/{d}"
  try: events+=get(url).get("events",[]); time.sleep(.5)
  except Exception: continue
 for f in fs:
  kick=datetime.fromisoformat(f["kickoff_hkt"])
  for side,other in (("home","away"),("away","home")):
   hid=f[f"{side}_hkjc_id"]
   if (hid,"sofascore") in known or hid in attempted:continue
   attempted.add(hid); hn=f[f"{side}_en"]; on=f[f"{other}_en"]; hc=cohort(hn)
   cand=[]
   for e in events:
    try:
     ek=datetime.fromtimestamp(e["startTimestamp"],timezone.utc).astimezone(HKT)
     if abs((ek-kick).total_seconds())>1800:continue
     et=e[side+"Team"]; ot=e[other+"Team"]
     if cohort(et.get("name",""))!=hc:continue
     s1=sim(hn,et.get("name",""));s2=sim(on,ot.get("name",""))
     if s1>=.62 and s2>=.62:cand.append((round((s1+s2)/2,3),e,et,ek))
    except Exception:pass
   cand.sort(key=lambda x:x[0],reverse=True)
   if len(cand)!=1 or cand[0][0]<.72:continue
   score,e,et,ek=cand[0]
   added.append({"hkjc_team_id":hid,"hkjc_name_en":hn,"hkjc_name_ch":f.get(f"{side}_ch",""),"cohort":hc,"external_source":"sofascore","external_team_id":str(et["id"]),"external_name":et.get("name",""),"evidence_class":"CONFIRMED_FACT","confirmed":"true","confidence":str(score),"source_url":f"{BASE}/sport/football/scheduled-events/{ek.date().isoformat()}","source_timestamp":ek.isoformat(),"fetched_at":datetime.now(timezone.utc).isoformat(),"raw_context":json.dumps({"hkjc_event_id":f["hkjc_event_id"],"sofascore_event_id":e.get("id"),"kickoff_delta_seconds":abs((ek-kick).total_seconds())},separators=(",",":"))})
 if added:
  exists=Path(a.registry).exists()
  with open(a.registry,"a",encoding="utf-8-sig",newline="") as out:
   w=csv.DictWriter(out,fieldnames=FIELDS); 
   if not exists:w.writeheader()
   w.writerows(added)
 print(f"PHASE2_SOFASCORE attempted={len(attempted)} confirmed_new={len(added)}")
if __name__=="__main__":main()
