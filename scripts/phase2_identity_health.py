"""Phase 2 Layer 1 health/exit gate. Fails CI on empty/stale current universe."""
import argparse,csv,json
from datetime import datetime,timedelta,timezone
from pathlib import Path
HKT=timezone(timedelta(hours=8))
def read(p):
 with open(p,encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def yes(v):return str(v).lower() in ("1","true","yes")
def main():
 p=argparse.ArgumentParser();p.add_argument("--fixtures",default="data/phase2_hkjc_current.csv");p.add_argument("--registry",default="data/phase2_team_identity_evidence.csv");p.add_argument("--out",default="data/phase2_identity_health.json");a=p.parse_args()
 fs=read(a.fixtures); reg=read(a.registry) if Path(a.registry).exists() else []
 teams={x for f in fs for x in (f["home_hkjc_id"],f["away_hkjc_id"]) if x}
 fetched=[datetime.fromisoformat(f["fetched_at_hkt"]) for f in fs if f.get("fetched_at_hkt")]
 age=max(0,(datetime.now(HKT)-max(fetched)).total_seconds()/3600) if fetched else 999
 by={}
 for r in reg:
  if yes(r.get("confirmed")) and r.get("external_team_id"):by.setdefault(r.get("hkjc_team_id"),set()).add((r.get("external_source"),r.get("external_team_id")))
 conflicts={k for k,v in by.items() if len(v)>1}; confirmed={k for k in teams if k in by and k not in conflicts}
 unresolved=teams-confirmed; coverage=100*len(confirmed)/len(teams) if teams else 0
 status="OK" if fs and age<=3 else "FAIL_STALE_OR_EMPTY"
 d={"status":status,"matches":len(fs),"unique_teams":len(teams),"confirmed":len(confirmed),"unresolved":len(unresolved),"conflicts":len(conflicts),"coverage_pct":round(coverage,1),"snapshot_age_hours":round(age,2),"layer1_exit":bool(status=="OK" and coverage>=90 and not conflicts)}
 Path(a.out).write_text(json.dumps(d,indent=2)+"\n",encoding="utf-8")
 print("PHASE2_HEALTH "+json.dumps(d,separators=(",",":")))
 if status!="OK":raise SystemExit(2)
if __name__=="__main__":main()
