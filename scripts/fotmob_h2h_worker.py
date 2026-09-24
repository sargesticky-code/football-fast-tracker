"""Slow Phase-1 FotMob direct-H2H worker."""
from __future__ import annotations
import argparse,csv,json,os
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from scripts.fotmob_h2h import Fixture,FotMobClient,match_fixture,normalize_h2h,parse_datetime,summarize
except ModuleNotFoundError:
    from fotmob_h2h import Fixture,FotMobClient,match_fixture,normalize_h2h,parse_datetime,summarize

ROOT=Path(__file__).resolve().parent.parent
CURRENT=ROOT/"data"/"hkjc_current_teams.csv"
ALIASES=ROOT/"data"/"fotmob_alias_master.csv"
OUT=ROOT/"data"/"fotmob_h2h_current.csv"
HKT=ZoneInfo("Asia/Hong_Kong")
MAX_DETAILS=max(0,int(os.getenv("FOTMOB_H2H_MAX_DETAILS","50")))

FIELDS=["fetched_at_utc","hkjc_event_id","kickoff_hkt","home_id","away_id","home","away",
"fotmob_match_id","fotmob_home_id","fotmob_away_id","fotmob_home","fotmob_away","fotmob_league",
"kickoff_delta_seconds","mapping_status","mapping_reason","h2h_games","home_wins","draws","away_wins",
"home_goals","away_goals","avg_total_goals","last5","meetings_json","source","quality"]


def clean(v): return "" if v is None else str(v).strip()

def read(path):
    if not path.exists(): return []
    with path.open(encoding="utf-8-sig",newline="") as fh: return list(csv.DictReader(fh))

def write(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8-sig",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=FIELDS,extrasaction="ignore"); w.writeheader()
        for row in rows: w.writerow({k:row.get(k,"") for k in FIELDS})
    tmp.replace(path)

def alias_map(rows):
    out={}
    for r in rows:
        canonical=clean(r.get("hkjc_name_en")); source=clean(r.get("source_name"))
        if canonical and source: out.setdefault(canonical,set()).add(source)
    return out

def fixtures(rows):
    out=[]
    for r in rows:
        dt=parse_datetime(r.get("kickoff_hkt"))
        if not dt or not clean(r.get("hkjc_event_id")) or not clean(r.get("home")) or not clean(r.get("away")):
            continue
        out.append((r,Fixture(clean(r["hkjc_event_id"]),dt,clean(r["home"]),clean(r["away"]),clean(r.get("tournament")))))
    return out

def board_dates(items):
    dates=set()
    for _,f in items:
        dates.add(f.kickoff.astimezone(timezone.utc).strftime("%Y%m%d"))
        dates.add(f.kickoff.astimezone(HKT).strftime("%Y%m%d"))
    return sorted(dates)

def build(current_rows,alias_rows,client,max_details=MAX_DETAILS,previous_rows=None):
    items=fixtures(current_rows); amap=alias_map(alias_rows)
    previous_rows=previous_rows or []
    previous_by_event={clean(r.get("hkjc_event_id")):r for r in previous_rows if clean(r.get("hkjc_event_id"))}
    boards=[]; board_errors=[]
    for day in board_dates(items):
        try: boards.append(client.matches(day))
        except Exception as exc: board_errors.append(f"{day}:{exc.__class__.__name__}")
    fetched=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out=[]; details_calls=0
    for raw,fixture in items:
        mapping=match_fixture(fixture,boards,aliases=amap)
        if not boards and mapping.status=="UNMAPPED":
            mapping=type(mapping)("SOURCE_UNAVAILABLE","board_fetch_failed")
        prior=previous_by_event.get(fixture.hkjc_event_id)
        prior_usable=bool(
            prior
            and clean(prior.get("quality")) in {"H2H_OK","NO_HISTORY"}
            and clean(prior.get("home"))==fixture.home
            and clean(prior.get("away"))==fixture.away
            and clean(prior.get("fotmob_match_id"))
        )
        base={
            "fetched_at_utc":fetched,"hkjc_event_id":fixture.hkjc_event_id,
            "kickoff_hkt":fixture.kickoff.astimezone(HKT).isoformat(),
            "home_id":clean(raw.get("home_id")),"away_id":clean(raw.get("away_id")),
            "home":fixture.home,"away":fixture.away,
            "fotmob_match_id":mapping.match_id or "","fotmob_home_id":mapping.home_team_id or "",
            "fotmob_away_id":mapping.away_team_id or "","fotmob_home":mapping.home_name,
            "fotmob_away":mapping.away_name,"fotmob_league":mapping.league,
            "kickoff_delta_seconds":"" if mapping.kickoff_delta_seconds is None else f"{mapping.kickoff_delta_seconds:.0f}",
            "mapping_status":mapping.status,"mapping_reason":mapping.reason,"source":"FOTMOB",
        }
        # Reuse stable prematch H2H evidence for the same HKJC event instead of
        # re-fetching it every run. This makes the detail budget rotate naturally
        # toward previously deferred/unresolved matches and preserves last-good
        # data during a transient board failure.
        if prior_usable and (
            mapping.status!="VERIFIED"
            or clean(prior.get("fotmob_match_id"))==str(mapping.match_id)
        ):
            keep={**prior,**base}
            keep["mapping_status"]="VERIFIED"
            keep["mapping_reason"]="reused_verified_h2h"
            keep["quality"]=clean(prior.get("quality"))
            for key in ("h2h_games","home_wins","draws","away_wins","home_goals","away_goals",
                        "avg_total_goals","last5","meetings_json"):
                keep[key]=prior.get(key,"")
            out.append(keep)
            continue
        if mapping.status!="VERIFIED":
            out.append({**base,"h2h_games":0,"home_wins":0,"draws":0,"away_wins":0,"home_goals":0,"away_goals":0,
                        "avg_total_goals":"","last5":"","meetings_json":"[]","quality":mapping.status})
            continue
        if details_calls>=max_details:
            out.append({**base,"h2h_games":0,"home_wins":0,"draws":0,"away_wins":0,"home_goals":0,"away_goals":0,
                        "avg_total_goals":"","last5":"","meetings_json":"[]","quality":"DEFERRED_BUDGET"})
            continue
        try:
            payload=client.match_details(mapping.match_id); details_calls+=1
            meetings=normalize_h2h(payload,current_home_team_id=mapping.home_team_id,current_away_team_id=mapping.away_team_id)
            summary=summarize(meetings)
            out.append({**base,**{k:v for k,v in summary.items() if k!="meetings"},
                        "avg_total_goals":"" if summary["avg_total_goals"] is None else f"{summary['avg_total_goals']:.2f}",
                        "meetings_json":json.dumps(meetings,ensure_ascii=False,separators=(",",":"))})
        except Exception:
            out.append({**base,"h2h_games":0,"home_wins":0,"draws":0,"away_wins":0,"home_goals":0,"away_goals":0,
                        "avg_total_goals":"","last5":"","meetings_json":"[]","quality":"SOURCE_UNAVAILABLE"})
    out.sort(key=lambda r:(r["kickoff_hkt"],r["hkjc_event_id"]))
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",default=str(CURRENT)); ap.add_argument("--aliases",default=str(ALIASES))
    ap.add_argument("--output",default=str(OUT)); ap.add_argument("--max-details",type=int,default=MAX_DETAILS); args=ap.parse_args()
    rows=read(Path(args.input))
    if not rows: raise SystemExit(f"no HKJC fixture rows in {args.input}")
    output_path=Path(args.output)
    previous=read(output_path)
    out=build(rows,read(Path(args.aliases)),FotMobClient(),max(0,args.max_details),previous_rows=previous)
    write(output_path,out)
    counts={}
    for r in out: counts[r["quality"]]=counts.get(r["quality"],0)+1
    mapped=sum(r["mapping_status"]=="VERIFIED" for r in out)
    print("FOTMOB_H2H "+f"fixtures={len(out)} mapped={mapped} "+ " ".join(f"{k}={v}" for k,v in sorted(counts.items())))
    return 0

if __name__=="__main__": raise SystemExit(main())
