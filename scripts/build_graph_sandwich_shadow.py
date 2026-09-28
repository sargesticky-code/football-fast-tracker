#!/usr/bin/env python3
"""Graph Sandwich Phase 1 shadow graph builder.

Builds a deterministic, lightweight relationship graph from the canonical HKJC
snapshot. It never changes betting recommendations. Output is JSON that can be
consumed by later PyG/NetworkX adapters and the dashboard WHY chain.
"""
from __future__ import annotations
import argparse, csv, json
from pathlib import Path
from datetime import datetime, timezone

MARKETS=(("HDA",("had_home","had_draw","had_away")),("GOALS",("hil_over","hil_under")),("CORNERS",("chl_over","chl_under")))

def present(v): return bool((v or "").strip())

def build(rows):
    nodes, edges = {}, []
    def node(i,t,**attrs): nodes.setdefault(i,{"id":i,"type":t,**attrs})
    def edge(a,b,r,**attrs): edges.append({"source":a,"target":b,"relation":r,**attrs})
    for r in rows:
        mid=(r.get("hkjc_event_id") or r.get("match_id") or "").strip()
        if not mid: continue
        m=f"match:{mid}"
        node(m,"MATCH",kickoff=r.get("kickoff_hkt"),status=r.get("status"),league=r.get("tournament"))
        for side in ("home","away"):
            name=(r.get(f"{side}_zh") or r.get(f"{side}_en") or "").strip()
            if name:
                tid=f"team:{name.casefold()}"
                node(tid,"TEAM",name=name)
                edge(tid,m,"PLAYS_IN",side=side.upper())
        for market, cols in MARKETS:
            vals={c:r.get(c) for c in cols if present(r.get(c))}
            if vals:
                mk=f"{m}:market:{market.lower()}"
                node(mk,"MARKET",market=market,values=vals,updated_at=r.get("odds_updated_at"))
                edge(m,mk,"HAS_MARKET")
        src=f"{m}:source:hkjc"
        node(src,"SOURCE",source="HKJC",fetched_at=r.get("fetched_at_hkt"))
        edge(src,m,"OBSERVES")
    return {"schema":"GS_SHADOW_V1","generated_at":datetime.now(timezone.utc).isoformat(),"nodes":list(nodes.values()),"edges":edges,
            "stats":{"matches":sum(n["type"]=="MATCH" for n in nodes.values()),"teams":sum(n["type"]=="TEAM" for n in nodes.values()),"markets":sum(n["type"]=="MARKET" for n in nodes.values()),"edges":len(edges)}}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",default="data/hkjc_current.csv"); p.add_argument("--output",default="data/graph_sandwich_shadow.json"); a=p.parse_args()
    with open(a.input,encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
    out=build(rows); Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print("GRAPH_SANDWICH_PHASE1",json.dumps(out["stats"],ensure_ascii=False))
if __name__=="__main__": main()
