#!/usr/bin/env python3
"""Targeted Phase-2 Layer-6 historical XI capture from FotMob.

Only current HKJC teams with confirmed FotMob IDs are queried. Bounded to recent
completed fixtures; accepts FACT evidence only when an explicit complete XI of
11 unique starters is present. No API-Football calls.
"""
import csv,json,time
from datetime import datetime,timezone
from pathlib import Path
import requests

DATA=Path("data"); IDENT=DATA/"phase2_team_identity_evidence.csv"; OUT=DATA/"phase2_historical_xi.csv"; HEALTH=DATA/"phase2_historical_xi_health.json"
MAX_TEAMS=40; MAX_MATCHES=2
S=requests.Session(); S.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json"})

def read(p):
    if not p.exists(): return []
    with p.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def get(url):
    r=S.get(url,timeout=20); r.raise_for_status(); return r.json()
def completed(m):
    st=m.get("status") or {}
    return bool(st.get("finished") or st.get("cancelled") is False and st.get("started") and st.get("scoreStr"))
def fixture_rows(obj):
    fs=(obj.get("fixtures") or {}).get("allFixtures") or (obj.get("fixtures") or {}).get("fixtures") or []
    return fs if isinstance(fs,list) else []
def starters(detail,team_id):
    content=detail.get("content") or {}; lu=content.get("lineup") or {}
    teams=lu.get("lineup") or lu.get("teams") or []
    if isinstance(teams,dict): teams=list(teams.values())
    for t in teams if isinstance(teams,list) else []:
        tid=str(t.get("teamId") or (t.get("team") or {}).get("id") or "")
        if tid!=str(team_id): continue
        arr=t.get("starters") or t.get("players") or []
        ids=[]
        for p in arr if isinstance(arr,list) else []:
            if p.get("isStarter") is False: continue
            pid=p.get("id") or p.get("playerId") or (p.get("player") or {}).get("id")
            if pid is not None: ids.append(str(pid))
        ids=list(dict.fromkeys(ids))
        if len(ids)==11:return ids
    return []

existing=read(OUT); keys={(r.get("hkjc_team_id"),r.get("fotmob_match_id")) for r in existing}
ids={}
for r in read(IDENT):
    if str(r.get("confirmed","")).lower()=="true" and r.get("external_source")=="fotmob" and r.get("external_team_id"):
        ids[r["hkjc_team_id"]]=(r["external_team_id"],r.get("hkjc_name_en",""))
targets=list(ids.items())[:MAX_TEAMS]
new=[]; failures={}
for hkid,(fid,name) in targets:
    try:
        team=get(f"https://www.fotmob.com/api/teams?id={fid}")
        candidates=[m for m in fixture_rows(team) if completed(m)]
        candidates=sorted(candidates,key=lambda m:str(m.get("status",{}).get("utcTime") or m.get("time") or ""),reverse=True)[:MAX_MATCHES]
        if not candidates: failures["NO_COMPLETED_FIXTURE"]=failures.get("NO_COMPLETED_FIXTURE",0)+1
        for m in candidates:
            mid=str(m.get("id") or m.get("matchId") or "")
            if not mid or (hkid,mid) in keys: continue
            try:
                d=get(f"https://www.fotmob.com/api/matchDetails?matchId={mid}")
                xi=starters(d,fid)
                if len(xi)!=11:
                    failures["NO_EXPLICIT_COMPLETE_XI"]=failures.get("NO_EXPLICIT_COMPLETE_XI",0)+1; continue
                ko=(d.get("general") or {}).get("matchTimeUTC") or (m.get("status") or {}).get("utcTime") or ""
                new.append({"hkjc_team_id":hkid,"hkjc_team_name":name,"external_team_id":fid,"fotmob_match_id":mid,"kickoff_utc":ko,"starter_player_ids":"|".join(xi),"starter_count":11,"evidence_class":"FACT","confirmed":"true","confidence":"1.0","source":f"https://www.fotmob.com/api/matchDetails?matchId={mid}","fetched_at":datetime.now(timezone.utc).isoformat()})
                keys.add((hkid,mid))
            except Exception: failures["MATCH_DETAIL_SOURCE_FAILURE"]=failures.get("MATCH_DETAIL_SOURCE_FAILURE",0)+1
            time.sleep(.15)
    except Exception: failures["TEAM_SOURCE_FAILURE"]=failures.get("TEAM_SOURCE_FAILURE",0)+1
    time.sleep(.15)
rows=existing+new
fields=["hkjc_team_id","hkjc_team_name","external_team_id","fotmob_match_id","kickoff_utc","starter_player_ids","starter_count","evidence_class","confirmed","confidence","source","fetched_at"]
with OUT.open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
counts={}
for r in rows: counts[r["hkjc_team_id"]]=counts.get(r["hkjc_team_id"],0)+1
health={"layer":6,"generated_at":datetime.now(timezone.utc).isoformat(),"targeted_teams":len(targets),"new_verified_xi":len(new),"verified_xi_rows":len(rows),"teams_with_2plus_verified_xi":sum(v>=2 for v in counts.values()),"failure_classes":failures,"api_football_requests":0}
HEALTH.write_text(json.dumps(health,indent=2)+"\n",encoding="utf-8")
print(json.dumps(health))
