"""Targeted Phase-2 identity fallback using TheSportsDB public event endpoints."""
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
 ap=argparse.ArgumentParser();ap.add_argument("--fixtures",default="data/phase2_hkjc_current.csv");ap.add_argument("--registry",default="data/phase2_team_identity_evidence.csv");ap.add_argument("--diagnostics",default="data/phase2_thesportsdb_diagnostics.csv");a=ap.parse_args()
 fs=rows(a.fixtures);reg=rows(a.registry);known={(x.get("hkjc_team_id"),x.get("external_source")) for x in reg if str(x.get("confirmed","")).lower() in ("true","1","yes")}
 dates=sorted({datetime.fromisoformat(f["kickoff_hkt"]).date().isoformat() for f in fs}); events=[]; errors=[]; counts={}; now=datetime.now(timezone.utc).isoformat()
 for d in dates:
  url=f"{BASE}?d={d}&s=Soccer"
  try:r=requests.get(url,timeout=15,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"});r.raise_for_status();batch=r.json().get("events") or [];counts[d]=len(batch);events+=batch;time.sleep(.5)
  except Exception as e:errors.append([d,type(e).__name__,getattr(getattr(e,"response",None),"status_code",None)])
 added=[];attempted=set();fail={};search_requests=0;diag=[]
 for f in fs:
  kick=datetime.fromisoformat(f["kickoff_hkt"])
  for side,other in (("home","away"),("away","home")):
   hid=f[f"{side}_hkjc_id"]
   if (hid,"thesportsdb") in known or hid in attempted:continue
   attempted.add(hid);hn=f[f"{side}_en"];on=f[f"{other}_en"];hc=cohort(hn);cand=[];raw=[];search_status="NOT_RUN"
   for e in events:
    ek=event_dt(e)
    if not ek:continue
    en=e.get("strHomeTeam" if side=="home" else "strAwayTeam","");eo=e.get("strAwayTeam" if side=="home" else "strHomeTeam","");delta=abs((ek-kick).total_seconds());s1,s2=sim(hn,en),sim(on,eo)
    if delta<=1800:raw.append((delta,s1,s2,cohort(en),en,eo))
    if delta<=1800 and cohort(en)==hc and s1>=.62 and s2>=.62:cand.append((round((s1+s2)/2,3),e,en,ek))
   if not cand and search_requests<60:
    try:
     q=f["home_en"]+" vs "+f["away_en"];sr=requests.get(SEARCH,params={"e":q},timeout=15,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"});search_requests+=1;search_status=str(sr.status_code);sevents=(sr.json().get("event") or []) if sr.status_code==200 else []
     for se in sevents:
      sek=event_dt(se)
      if not sek:continue
      sen=se.get("strHomeTeam" if side=="home" else "strAwayTeam","");seo=se.get("strAwayTeam" if side=="home" else "strHomeTeam","");delta=abs((sek-kick).total_seconds());ss1,ss2=sim(hn,sen),sim(on,seo);raw.append((delta,ss1,ss2,cohort(sen),sen,seo))
      if delta<=1800 and cohort(sen)==hc and ss1>=.62 and ss2>=.62:cand.append((round((ss1+ss2)/2,3),se,sen,sek))
    except Exception as e:search_status=type(e).__name__
   cand.sort(key=lambda x:x[0],reverse=True)
   if len(cand)==1 and cand[0][0]>=.72:
    score,e,en,ek=cand[0];ext=e.get("idHomeTeam" if side=="home" else "idAwayTeam")
    if ext:
     added.append({"hkjc_team_id":hid,"hkjc_name_en":hn,"hkjc_name_ch":f.get(f"{side}_ch",""),"cohort":hc,"external_source":"thesportsdb","external_team_id":str(ext),"external_name":en,"evidence_class":"CONFIRMED_FACT","confirmed":"true","confidence":str(score),"source_url":SEARCH if search_status!="NOT_RUN" else BASE,"source_timestamp":ek.isoformat(),"fetched_at":now,"raw_context":json.dumps({"hkjc_event_id":f["hkjc_event_id"],"thesportsdb_event_id":e.get("idEvent")},separators=(",",":"))});continue
   if len(cand)>1:reason="AMBIGUOUS_CANDIDATES"
   elif not raw:reason="EVENT_ABSENT"
   elif min(x[0] for x in raw)>1800:reason="KICKOFF_MISMATCH"
   elif all(x[3]!=hc for x in raw):reason="COHORT_MISMATCH"
   else:reason="NAME_MISMATCH"
   fail[reason]=fail.get(reason,0)+1;best=max(raw,key=lambda x:(x[1]+x[2])) if raw else None
   diag.append({"hkjc_team_id":hid,"hkjc_name_en":hn,"hkjc_event_id":f["hkjc_event_id"],"reason":reason,"search_status":search_status,"candidate_count":len(cand),"best_candidate":json.dumps(best,ensure_ascii=False) if best else "","fetched_at":now})
 if added:
  exists=Path(a.registry).exists() and Path(a.registry).stat().st_size>0
  with open(a.registry,"a",encoding="utf-8-sig",newline="") as out:
   w=csv.DictWriter(out,fieldnames=FIELDS)
   if not exists:w.writeheader()
   w.writerows(added)
 if diag:
  with open(a.diagnostics,"w",encoding="utf-8-sig",newline="") as out:
   w=csv.DictWriter(out,fieldnames=diag[0].keys());w.writeheader();w.writerows(diag)
 print("PHASE2_THESPORTSDB "+json.dumps({"attempted":len(attempted),"confirmed_new":len(added),"unresolved":len(attempted)-len(added),"failure_classes":fail,"source_errors":errors,"source_event_counts":counts,"total_source_events":len(events),"targeted_search_requests":search_requests},separators=(",",":")))
if __name__=="__main__":main()
