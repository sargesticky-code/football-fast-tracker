"""Phase 2 Layer 1: independent read-only HKJC current-fixture capture."""
from __future__ import annotations
import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from vendor_hkjc_queries import ALL_MATCH_LIST

ENDPOINT = "https://info.cld.hkjc.com/graphql/base/"
HKT = timezone(timedelta(hours=8))
ENDED = {"MATCHENDED", "INPLAYMATCHENDED"}
FIELDS = ["fetched_at_hkt","match_id","hkjc_event_id","kickoff_hkt","status","tournament","tournament_en","home_hkjc_id","away_hkjc_id","home_en","away_en","home_ch","away_ch"]

def _headers():
    return {"Content-Type":"application/json","Origin":"https://bet.hkjc.com","Referer":"https://bet.hkjc.com/","User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"}

def _parse_hkjc_dt(value):
    value=(value or "").strip()
    if not value: raise ValueError("missing kickoff")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None: dt=dt.replace(tzinfo=HKT)
    return dt.astimezone(HKT)

def fetch_upcoming(horizon_hours=48, timeout=12):
    now=datetime.now(HKT); fetched_at=now.replace(microsecond=0).isoformat(); end=now+timedelta(hours=horizon_hours)
    response=requests.post(ENDPOINT,json={"query":ALL_MATCH_LIST,"variables":{}},headers=_headers(),timeout=timeout)
    response.raise_for_status(); body=response.json()
    if body.get("errors"): raise RuntimeError("HKJC GraphQL errors: "+repr(body["errors"]))
    raw=((body.get("data") or {}).get("matches") or []); rows=[]; seen=set()
    rejected={"ended":0,"outside_horizon":0,"bad_identity":0,"bad_kickoff":0}
    for match in raw:
        event_id=str(match.get("frontEndId") or "").strip(); status=str(match.get("status") or "").strip().upper()
        if status in ENDED: rejected["ended"]+=1; continue
        try: kickoff=_parse_hkjc_dt(str(match.get("kickOffTime") or match.get("matchDate") or ""))
        except (TypeError,ValueError): rejected["bad_kickoff"]+=1; continue
        if kickoff<now or kickoff>end: rejected["outside_horizon"]+=1; continue
        home=match.get("homeTeam") or {}; away=match.get("awayTeam") or {}
        home_id=str(home.get("id") or "").strip(); away_id=str(away.get("id") or "").strip(); home_en=str(home.get("name_en") or "").strip(); away_en=str(away.get("name_en") or "").strip()
        if not event_id.startswith("FB") or not home_id or not away_id or not home_en or not away_en: rejected["bad_identity"]+=1; continue
        if event_id in seen: continue
        seen.add(event_id); tourn=match.get("tournament") or {}
        rows.append({"fetched_at_hkt":fetched_at,"match_id":str(match.get("id") or "").strip(),"hkjc_event_id":event_id,"kickoff_hkt":kickoff.replace(microsecond=0).isoformat(),"status":status,"tournament":str(tourn.get("code") or "").strip(),"tournament_en":str(tourn.get("name_en") or "").strip(),"home_hkjc_id":home_id,"away_hkjc_id":away_id,"home_en":home_en,"away_en":away_en,"home_ch":str(home.get("name_ch") or "").strip(),"away_ch":str(away.get("name_ch") or "").strip()})
    rows.sort(key=lambda r:(r["kickoff_hkt"],r["hkjc_event_id"])); teams={r["home_hkjc_id"] for r in rows}|{r["away_hkjc_id"] for r in rows}
    health={"status":"OK" if rows else "OK_NO_UPCOMING","fetched_at_hkt":fetched_at,"raw_matches":len(raw),"upcoming_matches":len(rows),"unique_hkjc_teams":len(teams),"horizon_hours":horizon_hours,"request_count":1,**rejected}
    return rows,health

def write_csv(rows,path):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8-sig",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=FIELDS,extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    tmp.replace(path)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--out",default="data/phase2_hkjc_current.csv"); parser.add_argument("--horizon-hours",type=int,default=48); parser.add_argument("--health-out",default="data/phase2_hkjc_capture_health.json"); args=parser.parse_args()
    rows,health=fetch_upcoming(horizon_hours=max(1,args.horizon_hours)); write_csv(rows,Path(args.out))
    hp=Path(args.health_out); hp.parent.mkdir(parents=True,exist_ok=True); hp.write_text(json.dumps(health,indent=2)+"\n",encoding="utf-8")
    if not rows: raise RuntimeError("HKJC capture returned zero upcoming fixtures; refusing to persist a healthy state")
    print("PHASE2_HKJC "+" ".join(f"{k}={v}" for k,v in health.items())); return 0
if __name__=="__main__": raise SystemExit(main())
