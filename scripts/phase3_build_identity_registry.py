#!/usr/bin/env python3
"""Build Phase 3 Layer 2 identity registry from append-only JSONL evidence."""
import argparse, json
from pathlib import Path
from phase3.identity_registry import IdentityObservation, rebuild_registry

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--evidence",default="data/phase3_identity_evidence.jsonl")
    ap.add_argument("--out",default="data/phase3_live_identity_map.json")
    args=ap.parse_args()
    evidence=[]
    p=Path(args.evidence)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                evidence.append(IdentityObservation(**json.loads(line)))
    registry=rebuild_registry(evidence)
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    Path(args.out).write_text(json.dumps({"phase":3,"layer":2,"rows":registry},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    counts={s:sum(r["status"]==s for r in registry) for s in ("VERIFIED","CANDIDATE","CONFLICT")}
    print(f"PHASE3_LAYER2 evidence={len(evidence)} registry={len(registry)} verified={counts['VERIFIED']} candidate={counts['CANDIDATE']} conflict={counts['CONFLICT']}")
if __name__=="__main__":
    main()
