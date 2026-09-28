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
def num(v):
    try: return float(v)
    except (TypeError,ValueError): return None
def form_points(s):
    vals={"W":3,"D":1,"L":0}
    seq=[vals[x] for x in (s or "").upper() if x in vals]
    return sum(seq)/len(seq) if seq else None
def directional_evidence(fr,pr,preds):
    ev=[]
    if fr:
        hp,ap=form_points(fr.get("home_form6")),form_points(fr.get("away_form6"))
        if hp is not None and ap is not None and abs(hp-ap)>=0.5:
            side="HOME" if hp>ap else "AWAY"
            ev.append({"kind":"FORM","side":side,"strength":round(abs(hp-ap)/3,3),"text":"主隊近況較佳" if side=="HOME" else "客隊近況較佳"})
        hgf,hga,agf,aga=map(num,(fr.get("home_gf_avg"),fr.get("home_ga_avg"),fr.get("away_gf_avg"),fr.get("away_ga_avg")))
        if None not in (hgf,hga,agf,aga):
            hd=hgf-aga; ad=agf-hga
            if abs(hd-ad)>=0.6:
                side="HOME" if hd>ad else "AWAY"
                ev.append({"kind":"ATTACK_DEFENCE","side":side,"strength":round(min(abs(hd-ad)/3,1),3),"text":"主隊攻守數據較有利" if side=="HOME" else "客隊攻守數據較有利"})
    if pr:
        h,a=num(pr.get("home_rating")),num(pr.get("away_rating"))
        if h is not None and a is not None and abs(h-a)>=3:
            side="HOME" if h>a else "AWAY"
            ev.append({"kind":"OPTA_POWER","side":side,"strength":round(min(abs(h-a)/20,1),3),"text":"Opta實力評分偏主隊" if side=="HOME" else "Opta實力評分偏客隊"})
    for p in preds or []:
        rec=(p.get("recommendation") or "").lower()
        side="HOME" if any(x in rec for x in ("home","主"," h ","1")) else ("AWAY" if any(x in rec for x in ("away","客"," a ","2")) else "NEUTRAL")
        if side!="NEUTRAL": ev.append({"kind":"EXTERNAL_PREDICTION","side":side,"strength":num(p.get("match_score")) or 0.5,"text":f"{p.get('source') or 'External'}方向支持{'主隊' if side=='HOME' else '客隊'}"})
    return ev

def build(rows, form_rows=None, power_rows=None, prediction_rows=None):
    form_by_id={r.get('hkjc_event_id'):r for r in (form_rows or []) if r.get('hkjc_event_id')}
    power_by_id={r.get('hkjc_event_id'):r for r in (power_rows or []) if r.get('hkjc_event_id')}
    predictions_by_id={}
    for r in (prediction_rows or []):
        if r.get('hkjc_event_id'): predictions_by_id.setdefault(r['hkjc_event_id'],[]).append(r)
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
        fr=form_by_id.get(mid)
        if fr:
            fn=f"{m}:form"
            node(fn,"FORM",home_form6=fr.get("home_form6"),away_form6=fr.get("away_form6"),home_gf_avg=fr.get("home_gf_avg"),home_ga_avg=fr.get("home_ga_avg"),away_gf_avg=fr.get("away_gf_avg"),away_ga_avg=fr.get("away_ga_avg"),quality=fr.get("quality"),source=fr.get("source"))
            edge(fn,m,"EVIDENCE_FOR",kind="RECENT_FORM")
        pr=power_by_id.get(mid)
        if pr and (present(pr.get("home_rating")) or present(pr.get("away_rating"))):
            pn=f"{m}:model:opta_power"
            node(pn,"MODEL_SIGNAL",model="OPTA_POWER",home_rating=pr.get("home_rating"),away_rating=pr.get("away_rating"),coverage=pr.get("coverage"),source=pr.get("source"))
            edge(pn,m,"MODEL_EVIDENCE",kind="TEAM_STRENGTH")
        for idx,pred in enumerate(predictions_by_id.get(mid,[])):
            if present(pred.get("recommendation")):
                pn=f"{m}:prediction:{(pred.get('source') or 'unknown').lower()}:{idx}"
                node(pn,"PREDICTION",source=pred.get("source"),recommendation=pred.get("recommendation"),market=pred.get("market"),match_score=pred.get("match_score"),status=pred.get("status"))
                edge(pn,m,"MODEL_EVIDENCE",kind="EXTERNAL_PREDICTION")
        src=f"{m}:source:hkjc"
        node(src,"SOURCE",source="HKJC",fetched_at=r.get("fetched_at_hkt"))
        edge(src,m,"OBSERVES")
    why=[]
    match_rows={(r.get("hkjc_event_id") or r.get("match_id") or "").strip():r for r in rows}
    for n in nodes.values():
        if n["type"]!="MATCH": continue
        mid=n["id"]; rel=[e for e in edges if e["target"]==mid or e["source"]==mid]
        signals=[]
        raw_mid=mid.split(":",1)[1]
        evidence=directional_evidence(form_by_id.get(raw_mid),power_by_id.get(raw_mid),predictions_by_id.get(raw_mid,[]))
        home_support=sum(e["strength"] for e in evidence if e["side"]=="HOME")
        away_support=sum(e["strength"] for e in evidence if e["side"]=="AWAY")
        direction="HOME" if home_support-away_support>=0.35 else ("AWAY" if away_support-home_support>=0.35 else "MIXED")
        conflict=home_support>0 and away_support>0
        if any(e["relation"]=="EVIDENCE_FOR" for e in rel): signals.append("recent_form_available")
        model_count=sum(e["relation"]=="MODEL_EVIDENCE" for e in rel)
        if model_count: signals.append(f"model_signals:{model_count}")
        market_count=sum(e["relation"]=="HAS_MARKET" for e in rel)
        signals.append(f"market_groups:{market_count}")
        signals.append("hkjc_source_present" if any(e["relation"]=="OBSERVES" for e in rel) else "source_missing")
        why.append({"match_id":raw_mid,"why_chain":signals,"directional_evidence":evidence,"direction":direction,"conflict":conflict,"support":{"home":round(home_support,3),"away":round(away_support,3)},"confidence":"EVIDENCE_RICH" if market_count>=2 and len(evidence)>=2 else "PARTIAL_EVIDENCE"})
    return {"schema":"GS_SHADOW_V1","generated_at":datetime.now(timezone.utc).isoformat(),"nodes":list(nodes.values()),"edges":edges,"why_chains":why,
            "stats":{"matches":sum(n["type"]=="MATCH" for n in nodes.values()),"teams":sum(n["type"]=="TEAM" for n in nodes.values()),"markets":sum(n["type"]=="MARKET" for n in nodes.values()),"forms":sum(n["type"]=="FORM" for n in nodes.values()),"model_signals":sum(n["type"] in ("MODEL_SIGNAL","PREDICTION") for n in nodes.values()),"why_chains":len(why),"edges":len(edges)}}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",default="data/hkjc_current.csv"); p.add_argument("--form-input",default="data/team_form_summary.csv"); p.add_argument("--power-input",default="data/hkjc_power_current.csv"); p.add_argument("--prediction-input",default="data/prediction_fallback_current.csv"); p.add_argument("--output",default="data/graph_sandwich_shadow.json"); a=p.parse_args()
    with open(a.input,encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
    form_rows=[]
    fp=Path(a.form_input)
    if fp.exists():
        with fp.open(encoding="utf-8-sig",newline="") as f: form_rows=list(csv.DictReader(f))
    power_rows=[]; prediction_rows=[]
    for path,target in ((a.power_input,power_rows),(a.prediction_input,prediction_rows)):
        pp=Path(path)
        if pp.exists():
            with pp.open(encoding="utf-8-sig",newline="") as f: target.extend(csv.DictReader(f))
    out=build(rows,form_rows,power_rows,prediction_rows); Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print("GRAPH_SANDWICH_PHASE1",json.dumps(out["stats"],ensure_ascii=False))
if __name__=="__main__": main()
