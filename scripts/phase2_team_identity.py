"""Phase 2 Layer 1: persistent fail-closed team identity registry.

Consumes only Phase 2's independent HKJC fixture snapshot. Existing verified
external mappings are reused by stable HKJC team id. Unknown teams are emitted
as unresolved targets for targeted external discovery; ambiguous mappings never
become confirmed automatically.
"""
from __future__ import annotations
import argparse, csv
from datetime import datetime, timezone
from pathlib import Path

REGISTRY_FIELDS = [
 "hkjc_team_id","hkjc_name_en","hkjc_name_ch","cohort","external_source",
 "external_team_id","external_name","evidence_class","confirmed","confidence",
 "source_url","source_timestamp","fetched_at","raw_context"
]
TARGET_FIELDS = [
 "hkjc_team_id","hkjc_name_en","hkjc_name_ch","cohort","match_count",
 "next_kickoff_hkt","reason"
]
COHORTS=("WOMEN","U17","U18","U19","U20","U21","U23","RESERVE")

def cohort(*names):
 s=" ".join(names).upper()
 for c in COHORTS:
  if c in s or c.replace("U"," U") in s: return c
 return "SENIOR"

def read(path):
 if not path.exists(): return []
 with path.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))

def write(path,fields,rows):
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix(path.suffix+".tmp")
 with tmp.open("w",encoding="utf-8-sig",newline="") as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
 tmp.replace(path)

def truth(v): return str(v).strip().lower() in {"1","true","yes","y"}

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--fixtures",default="data/phase2_hkjc_current.csv")
 ap.add_argument("--registry",default="data/phase2_team_identity_evidence.csv")
 ap.add_argument("--targets",default="data/phase2_team_identity_targets.csv")
 a=ap.parse_args()
 fixtures=read(Path(a.fixtures)); registry=read(Path(a.registry))
 active={}
 for r in fixtures:
  for side in ("home","away"):
   tid=(r.get(side+"_hkjc_id") or "").strip()
   if not tid: continue
   x=active.setdefault(tid,{"en":(r.get(side+"_en") or "").strip(),"ch":(r.get(side+"_ch") or "").strip(),"games":0,"kickoffs":[]})
   x["games"]+=1
   if r.get("kickoff_hkt"):x["kickoffs"].append(r["kickoff_hkt"])
 confirmed={}
 conflicts=set()
 for r in registry:
  tid=(r.get("hkjc_team_id") or "").strip()
  if not tid or not truth(r.get("confirmed")) or not (r.get("external_team_id") or "").strip():continue
  key=((r.get("external_source") or "").strip().lower(),(r.get("external_team_id") or "").strip())
  old=confirmed.get(tid)
  if old and old!=key: conflicts.add(tid)
  else: confirmed[tid]=key
 targets=[]
 for tid,x in active.items():
  if tid in confirmed and tid not in conflicts:continue
  targets.append({"hkjc_team_id":tid,"hkjc_name_en":x["en"],"hkjc_name_ch":x["ch"],"cohort":cohort(x["en"],x["ch"]),"match_count":x["games"],"next_kickoff_hkt":min(x["kickoffs"]) if x["kickoffs"] else "","reason":"CONFLICT" if tid in conflicts else "NO_CONFIRMED_EXTERNAL_ID"})
 write(Path(a.targets),TARGET_FIELDS,sorted(targets,key=lambda r:(r["next_kickoff_hkt"],r["hkjc_team_id"])))
 covered=len(active)-len(targets)
 pct=round(100*covered/len(active),1) if active else 0
 print(f"PHASE2_IDENTITY active_teams={len(active)} confirmed={covered} unresolved={len(targets)} conflicts={len(conflicts)} coverage_pct={pct}")
 return 0
if __name__=="__main__": raise SystemExit(main())
