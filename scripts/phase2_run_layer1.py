"""Run complete isolated Phase-2 Layer-1 pipeline."""
from __future__ import annotations
import subprocess,sys
STEPS=[
 [sys.executable,"scripts/phase2_capture_hkjc.py","--out","data/phase2_hkjc_current.csv","--horizon-hours","48"],
 [sys.executable,"scripts/phase2_team_identity.py","--fixtures","data/phase2_hkjc_current.csv","--registry","data/phase2_team_identity_evidence.csv","--targets","data/phase2_team_identity_targets.csv"],
 [sys.executable,"scripts/phase2_resolve_sofascore.py","--fixtures","data/phase2_hkjc_current.csv","--registry","data/phase2_team_identity_evidence.csv"],
 [sys.executable,"scripts/phase2_resolve_thesportsdb.py","--fixtures","data/phase2_hkjc_current.csv","--registry","data/phase2_team_identity_evidence.csv"],
 [sys.executable,"scripts/phase2_resolve_espn.py","--fixtures","data/phase2_hkjc_current.csv","--registry","data/phase2_team_identity_evidence.csv"],
 [sys.executable,"scripts/phase2_resolve_fotmob.py","--fixtures","data/phase2_hkjc_current.csv","--registry","data/phase2_team_identity_evidence.csv"],
 [sys.executable,"scripts/phase2_team_identity.py","--fixtures","data/phase2_hkjc_current.csv","--registry","data/phase2_team_identity_evidence.csv","--targets","data/phase2_team_identity_targets.csv"],
 [sys.executable,"scripts/phase2_identity_health.py","--fixtures","data/phase2_hkjc_current.csv","--registry","data/phase2_team_identity_evidence.csv","--out","data/phase2_identity_health.json"],
]
for i,cmd in enumerate(STEPS,1):
 print(f"PHASE2_LAYER1 step={i}/{len(STEPS)} cmd={' '.join(cmd)}",flush=True);subprocess.run(cmd,check=True)
print("PHASE2_LAYER1 COMPLETE",flush=True)
