"""Build display-ready recent team form for current HKJC/Forebet fixtures.

Priority:
1) Forebet recent-form enrichment when available.
2) Official HKJC result history fallback.

This is descriptive static data, not a model. It intentionally works with fewer
than eight matches so the dashboard can show recent form even when the Poisson
Form model remains fail-closed.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent.parent
HISTORY=ROOT/"data"/"hkjc_history.csv"
TEAMS=ROOT/"data"/"hkjc_current_teams.csv"
FOREBET=ROOT/"data"/"forebet_form_current.csv"
OUT=ROOT/"data"/"team_form_summary.csv"
HKT=ZoneInfo("Asia/Hong_Kong")

FIELDS=[
    "fetched_at_hkt","hkjc_event_id","kickoff_hkt","home","away",
    "home_form6","away_form6",
    "home_games","away_games",
    "home_w","home_d","home_l","away_w","away_d","away_l",
    "home_gf_avg","home_ga_avg","away_gf_avg","away_ga_avg",
    "home_venue_form","away_venue_form",
    "home_form_text","away_form_text",
    "source","quality",
]

def read(path):
    if not path.exists(): return []
    with path.open(encoding="utf-8-sig",newline="") as fh:
        return list(csv.DictReader(fh))

def clean(v): return "" if v is None else str(v).strip()

def dt(v):
    s=clean(v)
    if not s: return None
    try: x=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError: return None
    if x.tzinfo is None: x=x.replace(tzinfo=HKT)
    return x.astimezone(HKT)

def recent_for_team(history,team_id,kickoff,venue=None,limit=6):
    rows=[]
    for r in history:
        hid=clean(r.get("home_id")); aid=clean(r.get("away_id"))
        if team_id not in (hid,aid): continue
        at_home=hid==team_id
        if venue=="H" and not at_home: continue
        if venue=="A" and at_home: continue
        when=dt(r.get("kickoff_hkt"))
        if not when or when>=kickoff: continue
        try:
            hg=int(float(r.get("home_goals",""))); ag=int(float(r.get("away_goals","")))
        except (TypeError,ValueError): continue
        gf,ga=(hg,ag) if at_home else (ag,hg)
        result="W" if gf>ga else ("D" if gf==ga else "L")
        rows.append((when,result,gf,ga))
    rows.sort(key=lambda x:x[0],reverse=True)
    return rows[:limit]

def summarize(rows):
    if not rows:
        return dict(seq="",n=0,w=0,d=0,l=0,gf="",ga="")
    seq="".join(x[1] for x in rows)
    n=len(rows); w=sum(x[1]=="W" for x in rows); d=sum(x[1]=="D" for x in rows); l=n-w-d
    gf=sum(x[2] for x in rows)/n; ga=sum(x[3] for x in rows)/n
    return dict(seq=seq,n=n,w=w,d=d,l=l,gf=f"{gf:.2f}",ga=f"{ga:.2f}")

def compact(s):
    if not s["n"]: return "無近期資料"
    return f'{s["seq"]} · {s["w"]}-{s["d"]}-{s["l"]} · GF {s["gf"]} / GA {s["ga"]}'

def main():
    history=read(HISTORY); teams=read(TEAMS); forebet=read(FOREBET)
    fb={clean(r.get("hkjc_event_id")):r for r in forebet if clean(r.get("hkjc_event_id")) and clean(r.get("status")) in ("OK","PARTIAL")}
    now=datetime.now(HKT).replace(microsecond=0)
    out=[]; fb_used=0; hkjc_used=0; empty=0

    for m in teams:
        eid=clean(m.get("hkjc_event_id")); kick=dt(m.get("kickoff_hkt"))
        if not eid or not kick: continue
        h= summarize(recent_for_team(history,clean(m.get("home_id")),kick))
        a= summarize(recent_for_team(history,clean(m.get("away_id")),kick))
        hv=summarize(recent_for_team(history,clean(m.get("home_id")),kick,"H"))
        av=summarize(recent_for_team(history,clean(m.get("away_id")),kick,"A"))

        row={
            "fetched_at_hkt":now.isoformat(),
            "hkjc_event_id":eid,
            "kickoff_hkt":kick.isoformat(timespec="minutes"),
            "home":clean(m.get("home")),"away":clean(m.get("away")),
            "home_form6":h["seq"],"away_form6":a["seq"],
            "home_games":h["n"],"away_games":a["n"],
            "home_w":h["w"],"home_d":h["d"],"home_l":h["l"],
            "away_w":a["w"],"away_d":a["d"],"away_l":a["l"],
            "home_gf_avg":h["gf"],"home_ga_avg":h["ga"],
            "away_gf_avg":a["gf"],"away_ga_avg":a["ga"],
            "home_venue_form":hv["seq"],"away_venue_form":av["seq"],
            "home_form_text":compact(h),"away_form_text":compact(a),
            "source":"HKJC matchResult",
            "quality":f'HKJC_RECENT:{h["n"]}/{a["n"]}',
        }

        f=fb.get(eid)
        if f:
            # Forebet is richer/current when available. Preserve HKJC fallback
            # for fields Forebet did not expose.
            row["home_form6"]=clean(f.get("home_form6")) or row["home_form6"]
            row["away_form6"]=clean(f.get("away_form6")) or row["away_form6"]
            for side in ("home","away"):
                fw=clean(f.get(f"{side}_last6_w"))
                fd=clean(f.get(f"{side}_last6_d"))
                fl=clean(f.get(f"{side}_last6_l"))
                if fw and fd and fl:
                    row[f"{side}_w"]=fw; row[f"{side}_d"]=fd; row[f"{side}_l"]=fl
                    row[f"{side}_games"]=int(fw)+int(fd)+int(fl)
                for suffix,src in (("gf_avg",f"{side}_gf_avg"),("ga_avg",f"{side}_ga_avg")):
                    if clean(f.get(src)): row[f"{side}_{suffix}"]=clean(f.get(src))
            if clean(f.get("home_form6")):
                row["home_form_text"]=f'{row["home_form6"]} · {row["home_w"]}-{row["home_d"]}-{row["home_l"]} · GF {row["home_gf_avg"]} / GA {row["home_ga_avg"]}'
            if clean(f.get("away_form6")):
                row["away_form_text"]=f'{row["away_form6"]} · {row["away_w"]}-{row["away_d"]}-{row["away_l"]} · GF {row["away_gf_avg"]} / GA {row["away_ga_avg"]}'
            row["source"]="Forebet recent form + HKJC fallback"
            row["quality"]="FOREBET_"+clean(f.get("status"))
            fb_used+=1
        elif h["n"] or a["n"]:
            hkjc_used+=1
        else:
            empty+=1
        out.append(row)

    tmp=OUT.with_suffix(".tmp")
    with tmp.open("w",encoding="utf-8-sig",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=FIELDS); w.writeheader()
        w.writerows({k:r.get(k,"") for k in FIELDS} for r in out)
    tmp.replace(OUT)
    print(f"TEAM_FORM_SUMMARY rows={len(out)} forebet={fb_used} hkjc={hkjc_used} empty={empty} history_rows={len(history)}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
