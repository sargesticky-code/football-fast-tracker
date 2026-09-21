#!/usr/bin/env python3
"""Build persistent Phase 3 Layer 2 identity registry from JSONL evidence."""
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from phase3.identity_registry import IdentityObservation, rebuild_registry, merge_terminal_registry
from phase3.identity_exceptions import resolve_verified_exceptions

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--evidence",default="data/phase3_identity_evidence.jsonl"); ap.add_argument("--out",default="data/phase3_live_identity_map.json"); ap.add_argument("--exceptions",default="data/phase3_identity_exceptions.json"); args=ap.parse_args()
    evidence=[]; p=Path(args.evidence); out=Path(args.out); exception_path=Path(args.exceptions)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip(): evidence.append(IdentityObservation(**json.loads(line)))
    previous=[]
    if out.exists():
        try: previous=json.loads(out.read_text(encoding="utf-8")).get("rows",[])
        except (OSError,ValueError,TypeError): previous=[]
    registry=merge_terminal_registry(previous,rebuild_registry(evidence))
    out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps({"phase":3,"layer":2,"rows":registry},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    resolved=0
    if exception_path.exists():
        try: exceptions=json.loads(exception_path.read_text(encoding="utf-8"))
        except (OSError,ValueError,TypeError): exceptions=[]
        before=sum(x.get("status")=="RESOLVED" for x in exceptions)
        exceptions=resolve_verified_exceptions(exceptions,registry,datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        after=sum(x.get("status")=="RESOLVED" for x in exceptions); resolved=max(0,after-before)
        exception_path.write_text(json.dumps(exceptions,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    statuses=("VERIFIED","CANDIDATE","CONFLICT","LOCKED_CONFLICT")
    counts={s:sum(r.get("status")==s for r in registry) for s in statuses}
    print(f"PHASE3_LAYER2 evidence={len(evidence)} registry={len(registry)} verified={counts['VERIFIED']} candidate={counts['CANDIDATE']} conflict={counts['CONFLICT']} locked_conflict={counts['LOCKED_CONFLICT']} exceptions_resolved={resolved}")
if __name__=="__main__": main()
