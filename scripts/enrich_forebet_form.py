"""Enrich current HKJC-matched fixtures with recent Forebet team-form data.

This is a static-data enrichment layer only.
- Uses the Forebet match-detail URL already captured by the core parser.
- Fetches at most the nearest 30 active fixtures per run.
- One Jina-rendered match page per fixture; no browser fan-out.
- Preserves last-good rows when a detail page is temporarily unavailable.
- Does not alter the 1X2 / O-U / corner model feed if form parsing fails.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "forebet_current.csv"
OUT = ROOT / "data" / "forebet_form_current.csv"
HKT = ZoneInfo("Asia/Hong_Kong")
JINA = "https://r.jina.ai/"
TIMEOUT = 55
MAX_MATCHES = 30

FIELDS = [
    "fetched_at_hkt","hkjc_event_id","kickoff_hkt","home_en","away_en",
    "source_url","status",
    "home_form6","away_form6",
    "home_last6_w","home_last6_d","home_last6_l","home_last6_ppg",
    "away_last6_w","away_last6_d","away_last6_l","away_last6_ppg",
    "home_home_w","home_home_d","home_home_l",
    "away_away_w","away_away_d","away_away_l",
    "home_gf_avg","home_ga_avg","away_gf_avg","away_ga_avg",
    "home_shots_avg","away_shots_avg",
    "home_possession_pct","away_possession_pct",
    "home_corners_avg","away_corners_avg",
    "quality_fields","notes",
]

def clean(v):
    return "" if v is None else str(v).strip()

def read_csv(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))

def parse_dt(v):
    s=clean(v)
    if not s:
        return None
    try:
        dt=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError:
        try:
            dt=datetime.strptime(s[:16],"%Y-%m-%d %H:%M")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt=dt.replace(tzinfo=HKT)
    return dt.astimezone(HKT)

def plain_line(v):
    v=re.sub(r"!\[[^\]]*\]\([^)]+\)"," ",v)
    v=re.sub(r"\[([^\]]+)\]\([^)]+\)",r"\1",v)
    v=v.replace("**","").replace("__","")
    v=re.sub(r"^#+\s*","",v)
    return " ".join(v.split()).strip()

def page_lines(body):
    return [x for x in (plain_line(v) for v in body.splitlines()) if x]

def section(lines, start_name, end_names):
    start=-1
    for i,line in enumerate(lines):
        if line.casefold()==start_name.casefold():
            start=i+1
            break
    if start<0:
        return ""
    end=len(lines)
    for i in range(start,len(lines)):
        if any(lines[i].casefold()==x.casefold() for x in end_names):
            end=i
            break
    return " ".join(lines[start:end])

def ppg(w,d,l):
    n=w+d+l
    return "" if not n else f"{(3*w+d)/n:.2f}"

def parse_form(body):
    lines=page_lines(body)
    if not lines:
        return {}, "EMPTY"

    joined=" ".join(lines)

    # The compact current-form strings are printed immediately around the
    # fixture heading on Forebet detail pages (e.g. LDDLWL / WLWDLL).
    seqs=[]
    for line in lines[:140]:
        if re.fullmatch(r"[WDL]{4,10}",line,re.I):
            seq=line.upper()
            if seq not in seqs:
                seqs.append(seq)
    if len(seqs)<2:
        for seq in re.findall(r"(?<![A-Z])([WDL]{4,10})(?![A-Z])",joined,re.I):
            seq=seq.upper()
            if seq not in seqs:
                seqs.append(seq)
            if len(seqs)>=2:
                break

    # Forebet repeats the standard "Win n p% Draw n p% Lost n p%" summary:
    # first two occurrences = each team's last-six; next pair = home/away split.
    wdl_matches=re.findall(
        r"Win\s+(\d+)\s+\d+%\s+Draw\s+(\d+)\s+\d+%\s+Lost\s+(\d+)\s+\d+%",
        joined, flags=re.I
    )
    wdl=[tuple(map(int,m)) for m in wdl_matches]

    out={
        "home_form6": seqs[0] if len(seqs)>0 else "",
        "away_form6": seqs[1] if len(seqs)>1 else "",
    }
    if len(wdl)>0:
        w,d,l=wdl[0]
        out.update(home_last6_w=w,home_last6_d=d,home_last6_l=l,home_last6_ppg=ppg(w,d,l))
    if len(wdl)>1:
        w,d,l=wdl[1]
        out.update(away_last6_w=w,away_last6_d=d,away_last6_l=l,away_last6_ppg=ppg(w,d,l))
    if len(wdl)>2:
        out.update(home_home_w=wdl[2][0],home_home_d=wdl[2][1],home_home_l=wdl[2][2])
    if len(wdl)>3:
        out.update(away_away_w=wdl[3][0],away_away_d=wdl[3][1],away_away_l=wdl[3][2])

    goals=section(lines,"Goals",["Shots"])
    gm=re.search(
        r"Scored\s+\d+\s+Avg\.\s+per game\s+([\d.]+)\s+"
        r"Conceded\s+\d+\s+Avg\.\s+per game\s+([\d.]+)\s+"
        r"Scored\s+\d+\s+Avg\.\s+per game\s+([\d.]+)\s+"
        r"Conceded\s+\d+\s+Avg\.\s+per game\s+([\d.]+)",
        goals, flags=re.I
    )
    if gm:
        out.update(
            home_gf_avg=gm.group(1),home_ga_avg=gm.group(2),
            away_gf_avg=gm.group(3),away_ga_avg=gm.group(4)
        )

    shots=section(lines,"Shots",["Passes"])
    sm=re.findall(r"Total shots\s+\d+\s+([\d.]+)",shots,flags=re.I)
    if len(sm)>=2:
        out.update(home_shots_avg=sm[0],away_shots_avg=sm[1])

    passes=section(lines,"Passes",["Avg. event time","Total attacks"])
    pm=re.findall(r"Ball Possession\s+(\d+)%",passes,flags=re.I)
    if len(pm)>=2:
        out.update(home_possession_pct=pm[0],away_possession_pct=pm[1])

    others=section(lines,"Others",["Disciplinary"])
    cm=re.search(r"([\d.]+)\s+\d+\s+Corners\s+\d+\s+([\d.]+)",others,flags=re.I)
    if cm:
        out.update(home_corners_avg=cm.group(1),away_corners_avg=cm.group(2))

    quality=sum(bool(clean(v)) for k,v in out.items() if k not in ("quality_fields","notes"))
    out["quality_fields"]=str(quality)
    status="OK" if quality>=8 else ("PARTIAL" if quality>0 else "NO_FORM_PARSE")
    return out,status

def fetch(url):
    headers={
        "X-Timeout":"30",
        "X-No-Cache":"true",
        "X-Cache-Tolerance":"0",
        "User-Agent":"Mozilla/5.0",
    }
    r=requests.get(JINA+url,headers=headers,timeout=TIMEOUT)
    if r.status_code!=200 or len(r.text)<1200:
        raise RuntimeError(f"HTTP_{r.status_code}_BYTES_{len(r.text)}")
    return r.text

def main():
    if not FEED.exists():
        raise SystemExit("missing forebet_current.csv")

    now=datetime.now(HKT)
    current=read_csv(FEED)
    previous={clean(r.get("hkjc_event_id")):r for r in read_csv(OUT) if clean(r.get("hkjc_event_id"))}

    targets=[]
    for r in current:
        eid=clean(r.get("hkjc_event_id"))
        kick=parse_dt(r.get("hkjc_kickoff_hkt") or r.get("kickoff_text"))
        if not eid or not kick or not (now-timedelta(hours=2) <= kick <= now+timedelta(hours=48)):
            continue
        targets.append((kick,r))
    targets.sort(key=lambda x:x[0])
    targets=targets[:MAX_MATCHES]

    fetched=now.isoformat(timespec="seconds")
    output=[]
    calls=0
    ok=partial=missing=errors=0

    for kick,r in targets:
        eid=clean(r.get("hkjc_event_id"))
        url=clean(r.get("forebet_detail_url"))
        base={k:"" for k in FIELDS}
        base.update({
            "fetched_at_hkt":fetched,
            "hkjc_event_id":eid,
            "kickoff_hkt":kick.isoformat(timespec="minutes"),
            "home_en":clean(r.get("hkjc_home_team") or r.get("home_team")),
            "away_en":clean(r.get("hkjc_away_team") or r.get("away_team")),
            "source_url":url,
        })

        if not url:
            old=previous.get(eid)
            if old and clean(old.get("status")) in ("OK","PARTIAL"):
                base.update(old)
                base["notes"]="LAST_GOOD · current feed has no detail URL"
                output.append(base)
            else:
                base["status"]="NO_DETAIL_URL"
                base["notes"]="Forebet list row did not expose match-detail URL"
                output.append(base)
                missing+=1
            continue

        try:
            body=fetch(url)
            calls+=1
            parsed,status=parse_form(body)
            base.update(parsed)
            base["status"]=status
            if status=="OK": ok+=1
            elif status=="PARTIAL": partial+=1
            else: errors+=1
        except Exception as exc:
            calls+=1
            old=previous.get(eid)
            if old and clean(old.get("status")) in ("OK","PARTIAL"):
                base.update(old)
                base["notes"]="LAST_GOOD · "+type(exc).__name__
            else:
                base["status"]="ERROR"
                base["notes"]=(type(exc).__name__+":"+str(exc))[:180]
                errors+=1
        output.append(base)

    tmp=OUT.with_suffix(".tmp")
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with tmp.open("w",encoding="utf-8-sig",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=FIELDS)
        w.writeheader()
        w.writerows([{k:r.get(k,"") for k in FIELDS} for r in output])
    tmp.replace(OUT)

    usable=sum(clean(r.get("status")) in ("OK","PARTIAL") for r in output)
    print(
        f"FOREBET_FORM targets={len(output)} usable={usable} ok={ok} partial={partial} "
        f"no_detail={missing} errors={errors} jina_calls={calls} max={MAX_MATCHES}"
    )
    return 0

if __name__=="__main__":
    raise SystemExit(main())
