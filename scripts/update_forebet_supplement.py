#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HKJC = DATA / "hkjc_current.csv"
OUT = DATA / "forebet_supplement_current.csv"
HKT = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
TIMEOUT = 18

INDEX_URLS = [
    "https://www.forebet.com/en/football-tips-and-predictions-for-today/",
    "https://www.forebet.com/football-tips-and-predictions-for-tomorrow?lang=en",
]

FIELDS = [
    "fetched_at_hkt","hkjc_event_id","kickoff_hkt","hkjc_league",
    "home_en","away_en","prob_home","prob_draw","prob_away",
    "prediction_1x2","predicted_score","avg_goals","source_url",
    "match_score","status","notes"
]

def clean(v):
    return "" if v is None else str(v).strip()

def norm(v):
    s = unicodedata.normalize("NFKD", clean(v))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("&"," and ")
    s = re.sub(r"['’`]", "", s)
    s = re.sub(r"\b(fc|cf|sc|afc|club|football|soccer|bk|if)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())

def toks(v):
    return {x for x in norm(v).split() if len(x) >= 3}

def similarity(home, away, href):
    bag=toks(urlparse(href).path.replace("-"," "))
    ht,at=toks(home),toks(away)
    if not ht or not at:
        return 0.0
    return ((len(ht & bag)/len(ht))+(len(at & bag)/len(at)))/2

def parse_dt(v):
    s=clean(v)
    if not s:
        return None
    try:
        dt=datetime.fromisoformat(s.replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=HKT)
        return dt.astimezone(HKT)
    except Exception:
        try:
            return datetime(1899,12,30,tzinfo=HKT)+timedelta(days=float(s))
        except Exception:
            return None

def read_csv(path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def get(url):
    r=requests.get(url,headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml"},timeout=TIMEOUT)
    r.raise_for_status()
    return r.text

def discover_links():
    links=set()
    for url in INDEX_URLS:
        raw=get(url)
        soup=BeautifulSoup(raw,"html.parser")
        for a in soup.find_all("a",href=True):
            href=urljoin(url,a["href"])
            if "/football/matches/" in href:
                links.add(href.split("?")[0].split("#")[0])
    return sorted(links)

def choose_link(t, links):
    ranked=[]
    for href in links:
        s=similarity(t["home_en"],t["away_en"],href)
        if s>=0.48:
            ranked.append((s,href))
    ranked.sort(reverse=True)
    if not ranked:
        return "",0.0
    if len(ranked)>1 and ranked[0][0]<0.90 and ranked[0][0]-ranked[1][0]<0.12:
        return "",ranked[0][0]
    return ranked[0][1],ranked[0][0]

def page_text(raw):
    soup=BeautifulSoup(raw,"html.parser")
    return " ".join(soup.stripped_strings)

def parse_prediction(url):
    text=html.unescape(page_text(get(url)))
    # First full-time 1X2 probability block on a Forebet match page.
    m=re.search(
        r"(?<!\d)(\d{1,2}|100)\s+(\d{1,2}|100)\s+(\d{1,2}|100)\s+([12X])\s+(\d+\s*-\s*\d+)\s+(?:\d+\s*-\s*\d+\s+)?(\d+(?:\.\d+)?)",
        text
    )
    if not m:
        return None
    return {
        "prob_home":m.group(1),
        "prob_draw":m.group(2),
        "prob_away":m.group(3),
        "prediction_1x2":m.group(4),
        "predicted_score":re.sub(r"\s+"," ",m.group(5)),
        "avg_goals":m.group(6),
    }

def main():
    now=datetime.now(HKT)
    targets=[]
    for r in read_csv(HKJC):
        kick=parse_dt(r.get("kickoff_hkt"))
        if not kick or not (now-timedelta(hours=2) <= kick <= now+timedelta(hours=48)):
            continue
        st=clean(r.get("status")).upper()
        if any(x in st for x in ("ENDED","VOID","CANCEL","ABANDON","FT")):
            continue
        eid=clean(r.get("hkjc_event_id"))
        if not eid:
            continue
        targets.append({
            "hkjc_event_id":eid,
            "kickoff_hkt":kick,
            "hkjc_league":clean(r.get("tournament")),
            "home_en":clean(r.get("home_en")),
            "away_en":clean(r.get("away_en")),
        })

    links=discover_links()
    fetched=now.isoformat(timespec="seconds")
    rows=[]
    for t in targets:
        row={k:"" for k in FIELDS}
        row.update({
            "fetched_at_hkt":fetched,
            "hkjc_event_id":t["hkjc_event_id"],
            "kickoff_hkt":t["kickoff_hkt"].isoformat(timespec="minutes"),
            "hkjc_league":t["hkjc_league"],
            "home_en":t["home_en"],
            "away_en":t["away_en"],
        })
        try:
            href,score=choose_link(t,links)
            row["match_score"]=f"{score:.3f}"
            if not href:
                row["status"]="NO_MATCH"
            else:
                row["source_url"]=href
                pred=parse_prediction(href)
                if pred:
                    row.update(pred)
                    row["status"]="OK"
                else:
                    row["status"]="NO_PREDICTION_PARSE"
        except Exception as e:
            row["status"]="ERROR_"+type(e).__name__
            row["notes"]=str(e)[:180]
        rows.append(row)

    with OUT.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows; links={len(links)}")

if __name__=="__main__":
    main()
