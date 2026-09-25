"""Phase 2 Layer 1 health/exit gate. Fails CI on empty/stale current universe."""
import argparse,csv,json
from datetime import datetime,timedelta,timezone
from pathlib import Path
HKT=timezone(timedelta(hours=8))
def read(p):
 with open(p,encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def yes(v):return str(v).lower() in ("1","true","yes")
def main():
 p=argparse.ArgumentParser();p.add_argument("--fixtures",default="data/phase2_hkjc_current.csv");p.add_argument("--registry",default="data/phase2_team_identity_evidence.csv");p.add_argument("--out",default="data/phase2_identity_health.json");p.add_argument("--fotmob-diagnostics",default="data/phase2_fotmob_diagnostics.csv");a=p.parse_args()
 fs=read(a.fixtures); reg=read(a.registry) if Path(a.registry).exists() else []
 teams={x for f in fs for x in (f["home_hkjc_id"],f["away_hkjc_id"]) if x}
 fetched=[datetime.fromisoformat(f["fetched_at_hkt"]) for f in fs if f.get("fetched_at_hkt")]
 age=max(0,(datetime.now(HKT)-max(fetched)).total_seconds()/3600) if fetched else 999
 by={}
 for r in reg:
  if yes(r.get("confirmed")) and r.get("external_team_id"):
   hid=r.get("hkjc_team_id"); src=r.get("external_source") or "UNKNOWN"
   by.setdefault(hid,{}).setdefault(src,set()).add(r.get("external_team_id"))
 # External IDs live in provider-specific namespaces. A conflict exists only when
 # the same HKJC team has multiple confirmed IDs from the SAME provider.
 conflicts={k for k,providers in by.items() if any(len(ids)>1 for ids in providers.values())}
 confirmed={k for k in teams if k in by and k not in conflicts}
 unresolved=teams-confirmed; coverage=100*len(confirmed)/len(teams) if teams else 0
 # Alternate Layer-1 exit: when the live universe expands faster than persistent
 # mappings, allow progress only if every residual current team has been explicitly
 # attempted by the targeted FotMob resolver and is fail-closed with an auditable
 # failure class. This implements the documented ">=90% OR fully evidenced residuals"
 # rule without turning name proximity into a confirmation.
 safe_classes={"EVENT_ABSENT","NAME_MISMATCH","KICKOFF_MISMATCH","COHORT_MISMATCH","AMBIGUOUS_CANDIDATES"}
 diag=read(a.fotmob_diagnostics) if Path(a.fotmob_diagnostics).exists() else []
 diag_by={r.get("hkjc_team_id"):r for r in diag if r.get("hkjc_team_id")}
 evidenced={hid for hid in unresolved if hid in diag_by and diag_by[hid].get("failure_class") in safe_classes}
 residual_all_evidenced=bool(unresolved) and evidenced==unresolved
 status="OK" if fs and age<=3 else "FAIL_STALE_OR_EMPTY"
 threshold_exit=coverage>=90
 evidence_exit=residual_all_evidenced
 d={"status":status,"matches":len(fs),"unique_teams":len(teams),"confirmed":len(confirmed),"unresolved":len(unresolved),"conflicts":len(conflicts),"coverage_pct":round(coverage,1),"snapshot_age_hours":round(age,2),"residual_evidenced":len(evidenced),"residual_all_evidenced":residual_all_evidenced,"exit_reason":"COVERAGE_GE_90" if threshold_exit else ("ALL_RESIDUALS_EVIDENCED" if evidence_exit else "INCOMPLETE"),"layer1_exit":bool(status=="OK" and not conflicts and (threshold_exit or evidence_exit))}
 Path(a.out).write_text(json.dumps(d,indent=2)+"\n",encoding="utf-8")
 print("PHASE2_HEALTH "+json.dumps(d,separators=(",",":")))
 if status!="OK":raise SystemExit(2)
if __name__=="__main__":main()
