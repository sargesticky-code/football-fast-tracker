"""Phase-2 Layer-1 targeted FotMob identity resolver.
Fetches only dates present in the current HKJC 48h fixture universe. A mapping is
confirmed only when kickoff, home/away direction, both team names and cohort agree.
Residual candidates are persisted for audit-driven repair; ambiguity remains fail-closed.
"""
from __future__ import annotations
import argparse,csv,json,re,time
from datetime import datetime,timedelta,timezone
from difflib import SequenceMatcher
from pathlib import Path
import requests
HKT=timezone(timedelta(hours=8)); BASE="https://www.fotmob.com/api/data/matches"
FIELDS=["hkjc_team_id","hkjc_name_en","hkjc_name_ch","cohort","external_source","external_team_id","external_name","evidence_class","confirmed","confidence","source_url","source_timestamp","fetched_at","raw_context"]
DIAG_FIELDS=["hkjc_event_id","hkjc_team_id","side","hkjc_name","other_hkjc_name","kickoff_hkt","expected_cohort","failure_class","near_count","named_count","cohort_count","best_external_name","best_other_external_name","best_external_team_id","best_match_id","best_kickoff_hkt","best_name_similarity","best_other_similarity","best_external_cohort","fetched_at"]
def rows(p):
 if not Path(p).exists(): return []
 with open(p,encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
ALIASES={
 "korearepublic":"southkorea","koreadpr":"northkorea","unitedarabemirates":"uae",
 "bayernmunich":"bayernmunchen","intermilan":"inter","hacken":"bkhacken",
 "deportivonublense":"nublense","ohleuven":"oudheverleeleuven",
 "wigan":"wiganathletic","oldham":"oldhamathletic","fleetwood":"fleetwoodtown"
}
def norm(s):
 x=re.sub(r"[^a-z0-9]+","",str(s).lower())
 for suffix in ("women","woman"):
  if x.endswith(suffix): x=x[:-len(suffix)]
 return ALIASES.get(x,x)
def sim(a,b):return SequenceMatcher(None,norm(a),norm(b)).ratio()
def cohort(name,tournament=""):
 s=(str(name)+" "+str(tournament)).upper()
 age=""
 for x in ("U17","U18","U19","U20","U21","U23"):
  if x in s: age=x; break
 women=("WOMEN" in s or "(W)" in s)
 if "ASIAN GAMES MEN" in s: age="U23"
 if "RESERVE" in s:return "RESERVE"
 if women and age:return "WOMEN_"+age
 if women:return "WOMEN"
 if age:return age
 return "SENIOR"
def event_dt(e):
 u=(e.get("status") or {}).get("utcTime")
 if u:
  try:return datetime.fromisoformat(u.replace("Z","+00:00")).astimezone(HKT)
  except Exception:pass
 ts=e.get("timeTS")
 if ts:
  try:return datetime.fromtimestamp(float(ts)/1000,timezone.utc).astimezone(HKT)
  except Exception:pass
 return None
def team_obj(e,side): return e.get(side) or {}
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--fixtures",default="data/phase2_hkjc_current.csv");ap.add_argument("--registry",default="data/phase2_team_identity_evidence.csv");ap.add_argument("--diagnostics",default="data/phase2_fotmob_diagnostics.csv");a=ap.parse_args()
 fs=rows(a.fixtures);reg=rows(a.registry); confirmed_ids={x.get("hkjc_team_id") for x in reg if str(x.get("confirmed","")).lower() in ("true","1","yes")}
 dates=sorted({datetime.fromisoformat(f["kickoff_hkt"]).date().strftime("%Y%m%d") for f in fs}); events=[]; errors=[]; counts={}; now=datetime.now(timezone.utc).isoformat()
 for d in dates:
  try:
   r=requests.get(BASE,params={"date":d},timeout=20,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json","Referer":"https://www.fotmob.com/"})
   if r.status_code!=200: errors.append([d,"HTTP",r.status_code,str(r.text)[:120]]); continue
   payload=r.json(); batch=[]
   for league in payload.get("leagues") or []: batch.extend(league.get("matches") or [])
   counts[d]=len(batch); events.extend(batch); time.sleep(.5)
  except Exception as e:errors.append([d,type(e).__name__,None,str(e)[:120]])
 added=[]; attempted=set(); fail={}; diagnostics=[]
 for f in fs:
  kick=datetime.fromisoformat(f["kickoff_hkt"])
  for side,other in (("home","away"),("away","home")):
   hid=f[f"{side}_hkjc_id"]
   if hid in confirmed_ids or hid in attempted:continue
   attempted.add(hid); hn=f[f"{side}_en"]; on=f[f"{other}_en"]; hc=cohort(hn,f.get("tournament_en","")); near=[]; named=[]; coh=[]; scored=[]
   for e in events:
    ek=event_dt(e)
    if not ek or abs((ek-kick).total_seconds())>1800:continue
    near.append(e); en=team_obj(e,side).get("name",""); eo=team_obj(e,other).get("name",""); s1,s2=sim(hn,en),sim(on,eo); scored.append((s1+s2,e,en,eo,ek,s1,s2))
    if s1>=.62 and s2>=.62:
     named.append(e)
     if cohort(en)==hc:coh.append((round((s1+s2)/2,3),e,en,ek))
   coh.sort(key=lambda x:x[0],reverse=True)
   if len(coh)==1 and coh[0][0]>=.72:
    score,e,en,ek=coh[0]; ext=team_obj(e,side).get("id")
    if ext:
     added.append({"hkjc_team_id":hid,"hkjc_name_en":hn,"hkjc_name_ch":f.get(f"{side}_ch",""),"cohort":hc,"external_source":"fotmob","external_team_id":str(ext),"external_name":en,"evidence_class":"CONFIRMED_FACT","confirmed":"true","confidence":str(score),"source_url":BASE+"?date="+ek.strftime("%Y%m%d"),"source_timestamp":ek.isoformat(),"fetched_at":now,"raw_context":json.dumps({"hkjc_event_id":f["hkjc_event_id"],"fotmob_match_id":e.get("id")},separators=(",",":"))});continue
   reason="SOURCE_ERROR" if errors and not events else "EVENT_ABSENT" if not near else "NAME_MISMATCH" if not named else "COHORT_MISMATCH" if not coh else "AMBIGUOUS_CANDIDATES"; fail[reason]=fail.get(reason,0)+1
   scored.sort(key=lambda x:x[0],reverse=True); best=scored[0] if scored else None
   diagnostics.append({"hkjc_event_id":f["hkjc_event_id"],"hkjc_team_id":hid,"side":side,"hkjc_name":hn,"other_hkjc_name":on,"kickoff_hkt":kick.isoformat(),"expected_cohort":hc,"failure_class":reason,"near_count":len(near),"named_count":len(named),"cohort_count":len(coh),"best_external_name":best[2] if best else "","best_other_external_name":best[3] if best else "","best_external_team_id":str(team_obj(best[1],side).get("id", "")) if best else "","best_match_id":str(best[1].get("id", "")) if best else "","best_kickoff_hkt":best[4].isoformat() if best else "","best_name_similarity":round(best[5],3) if best else "","best_other_similarity":round(best[6],3) if best else "","best_external_cohort":cohort(best[2]) if best else "","fetched_at":now})
 if added:
  exists=Path(a.registry).exists() and Path(a.registry).stat().st_size>0
  with open(a.registry,"a",encoding="utf-8-sig",newline="") as out:
   w=csv.DictWriter(out,fieldnames=FIELDS)
   if not exists:w.writeheader()
   w.writerows(added)
 with open(a.diagnostics,"w",encoding="utf-8-sig",newline="") as out:
  w=csv.DictWriter(out,fieldnames=DIAG_FIELDS);w.writeheader();w.writerows(diagnostics)
 print("PHASE2_FOTMOB "+json.dumps({"attempted":len(attempted),"confirmed_new":len(added),"unresolved":len(attempted)-len(added),"failure_classes":fail,"source_errors":errors,"source_event_counts":counts,"total_source_events":len(events),"diagnostic_rows":len(diagnostics)},separators=(",",":")))
if __name__=="__main__":main()
