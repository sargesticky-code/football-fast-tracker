"""Phase-2 Layer-1 targeted ESPN fallback for current HKJC fixture dates only."""
from __future__ import annotations
import argparse,csv,json,re,time
from datetime import datetime,timedelta,timezone
from difflib import SequenceMatcher
from pathlib import Path
import requests
HKT=timezone(timedelta(hours=8)); BASE="https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"
FIELDS=["hkjc_team_id","hkjc_name_en","hkjc_name_ch","cohort","external_source","external_team_id","external_name","evidence_class","confirmed","confidence","source_url","source_timestamp","fetched_at","raw_context"]
def rows(p):
 if not Path(p).exists():return []
 with open(p,encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def norm(s):return re.sub(r"[^a-z0-9]+","",str(s).lower())
def sim(a,b):return SequenceMatcher(None,norm(a),norm(b)).ratio()
def cohort(s):
 u=str(s).upper()
 for x in ("WOMEN","U17","U18","U19","U20","U21","U23","RESERVE"):
  if x in u:return x
 return "SENIOR"
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--fixtures",default="data/phase2_hkjc_current.csv");ap.add_argument("--registry",default="data/phase2_team_identity_evidence.csv");ap.add_argument("--diagnostics",default="data/phase2_espn_diagnostics.csv");a=ap.parse_args()
 fs=rows(a.fixtures);reg=rows(a.registry);confirmed={x.get("hkjc_team_id") for x in reg if str(x.get("confirmed","")).lower() in ("true","1","yes")};dates=sorted({datetime.fromisoformat(f["kickoff_hkt"]).date() for f in fs});events=[];errors=[];counts={};urls={};now=datetime.now(timezone.utc).isoformat()
 for d in dates:
  url=BASE+"?dates="+d.strftime("%Y%m%d")+"&limit=1000";urls[d.isoformat()]=url
  try:
   r=requests.get(url,timeout=20,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"});r.raise_for_status();batch=r.json().get("events") or [];counts[d.isoformat()]=len(batch);events+=batch;time.sleep(.4)
  except Exception as e:errors.append([d.isoformat(),type(e).__name__,getattr(getattr(e,"response",None),"status_code",None)])
 added=[];diag=[];attempted=set();fail={}
 for f in fs:
  kick=datetime.fromisoformat(f["kickoff_hkt"])
  for side,other in (("home","away"),("away","home")):
   hid=f[f"{side}_hkjc_id"]
   if hid in confirmed or hid in attempted:continue
   attempted.add(hid);hn=f[f"{side}_en"];on=f[f"{other}_en"];hc=cohort(hn);cand=[];near=[]
   for e in events:
    try:ek=datetime.fromisoformat(e["date"].replace("Z","+00:00")).astimezone(HKT)
    except Exception:continue
    comps=e.get("competitions") or []
    if not comps:continue
    cs=comps[0].get("competitors") or [];home=next((x for x in cs if x.get("homeAway")=="home"),None);away=next((x for x in cs if x.get("homeAway")=="away"),None)
    if not home or not away:continue
    me=home if side=="home" else away;opp=away if side=="home" else home;en=(me.get("team") or {}).get("displayName","");eo=(opp.get("team") or {}).get("displayName","");delta=abs((ek-kick).total_seconds());s1,s2=sim(hn,en),sim(on,eo)
    if delta<=1800:near.append((delta,s1,s2,cohort(en),en,eo))
    if delta<=1800 and cohort(en)==hc and s1>=.62 and s2>=.62:cand.append((round((s1+s2)/2,3),e,me,en,ek))
   cand.sort(key=lambda x:x[0],reverse=True)
   if len(cand)==1 and cand[0][0]>=.72:
    score,e,me,en,ek=cand[0];ext=(me.get("team") or {}).get("id")
    if ext:
     added.append({"hkjc_team_id":hid,"hkjc_name_en":hn,"hkjc_name_ch":f.get(f"{side}_ch",""),"cohort":hc,"external_source":"espn","external_team_id":str(ext),"external_name":en,"evidence_class":"CONFIRMED_FACT","confirmed":"true","confidence":str(score),"source_url":urls.get(ek.date().isoformat(),BASE),"source_timestamp":ek.isoformat(),"fetched_at":now,"raw_context":json.dumps({"hkjc_event_id":f["hkjc_event_id"],"espn_event_id":e.get("id")},separators=(",",":"))});continue
   reason="AMBIGUOUS_CANDIDATES" if len(cand)>1 else "EVENT_ABSENT" if not near else "COHORT_MISMATCH" if all(x[3]!=hc for x in near) else "NAME_MISMATCH";fail[reason]=fail.get(reason,0)+1;diag.append({"hkjc_team_id":hid,"hkjc_name_en":hn,"hkjc_event_id":f["hkjc_event_id"],"reason":reason,"near_count":len(near),"fetched_at":now})
 if added:
  with open(a.registry,"a",encoding="utf-8-sig",newline="") as out:csv.DictWriter(out,fieldnames=FIELDS).writerows(added)
 if diag:
  with open(a.diagnostics,"w",encoding="utf-8-sig",newline="") as out:w=csv.DictWriter(out,fieldnames=diag[0].keys());w.writeheader();w.writerows(diag)
 print("PHASE2_ESPN "+json.dumps({"attempted":len(attempted),"confirmed_new":len(added),"unresolved":len(attempted)-len(added),"failure_classes":fail,"source_errors":errors,"source_event_counts":counts,"total_source_events":len(events)},separators=(",",":")))
if __name__=="__main__":main()
