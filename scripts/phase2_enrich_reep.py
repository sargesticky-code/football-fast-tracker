"""Phase 2 Reep corroboration adapter.
Uses the public Reep football entity register only as a cross-provider identity
corroboration layer. It NEVER upgrades injuries, availability, lineups, or any
current football fact. v0 is frozen; rows are explicitly labelled CORROBORATION.
"""
from __future__ import annotations
import csv,json,time
from datetime import datetime,timezone,timedelta
from pathlib import Path
import requests

DATA=Path("data")
PLAYER=DATA/"phase2_player_master.csv"
MANAGER=DATA/"phase2_manager_master.csv"
OUT=DATA/"phase2_reep_crosswalk.csv"
HEALTH=DATA/"phase2_reep_health.json"
BASE="https://reep-api.rahulkeerthi2-95d.workers.dev"
TTL_HOURS=168
FIELDS=["entity_type","hkjc_team_id","hkjc_team_name","fotmob_id","canonical_name","reep_id","sofascore_id","transfermarkt_id","fbref_id","api_football_id","evidence_class","freshness","source_url","fetched_at"]

def read_csv(path):
    if not path.exists(): return []
    with path.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))

def cache_fresh():
    if not HEALTH.exists() or not OUT.exists(): return False
    try:
        h=json.loads(HEALTH.read_text(encoding="utf-8"))
        ts=datetime.fromisoformat(h["fetched_at"])
        return datetime.now(timezone.utc)-ts < timedelta(hours=TTL_HOURS)
    except Exception:return False

def chunks(xs,n=100):
    for i in range(0,len(xs),n):yield xs[i:i+n]

def resolve(items):
    rows=[];errors=0
    for batch in chunks(items):
        body={"items":[{"provider":"fotmob","id":x["fotmob_id"],"type":x["entity_type"]} for x in batch],
              "targets":["sofascore","transfermarkt","fbref","api_football"]}
        try:
            r=requests.post(BASE+"/batch/resolve",json=body,timeout=30,headers={"User-Agent":"football-fast-tracker-phase2/1.0"})
            r.raise_for_status(); data=r.json().get("results",[])
        except Exception:
            errors+=len(batch); continue
        for src,res in zip(batch,data):
            if not isinstance(res,dict) or res.get("error"): continue
            ext=res.get("external_ids") or {}
            rows.append({
                **src,
                "reep_id":res.get("reep_id",""),
                "sofascore_id":ext.get("sofascore",""),
                "transfermarkt_id":ext.get("transfermarkt",""),
                "fbref_id":ext.get("fbref",""),
                "api_football_id":ext.get("api_football",""),
                "evidence_class":"CORROBORATION",
                "freshness":"FROZEN_V0_DO_NOT_USE_AS_CURRENT_FACT",
                "source_url":BASE+"/batch/resolve",
                "fetched_at":datetime.now(timezone.utc).isoformat(),
            })
        time.sleep(.05)
    return rows,errors

def main():
    if cache_fresh():
        print("PHASE2_REEP status=CACHED freshness_hours_lt=168"); return
    items=[];seen=set()
    for r in read_csv(PLAYER):
        fid=str(r.get("player_id") or "")
        if fid and ("player",fid) not in seen:
            seen.add(("player",fid));items.append({"entity_type":"player","hkjc_team_id":r.get("hkjc_team_id",""),"hkjc_team_name":r.get("hkjc_team_name",""),"fotmob_id":fid,"canonical_name":r.get("canonical_name","")})
    for r in read_csv(MANAGER):
        fid=str(r.get("manager_id") or "")
        if fid and ("coach",fid) not in seen:
            seen.add(("coach",fid));items.append({"entity_type":"coach","hkjc_team_id":r.get("hkjc_team_id",""),"hkjc_team_name":r.get("hkjc_team_name",""),"fotmob_id":fid,"canonical_name":r.get("canonical_name","")})
    rows,errors=resolve(items)
    with OUT.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
    h={"status":"OK" if items else "NO_TARGETS","targets":len(items),"resolved":len(rows),"resolution_pct":round(100*len(rows)/len(items),1) if items else 0,"errors":errors,"register":"Reep v0 frozen public bridge","use":"identity corroboration only","fetched_at":datetime.now(timezone.utc).isoformat()}
    HEALTH.write_text(json.dumps(h,indent=2)+"\n",encoding="utf-8")
    print("PHASE2_REEP "+json.dumps(h,separators=(",",":")))

if __name__=="__main__":main()
