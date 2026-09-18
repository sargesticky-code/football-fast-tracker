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

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HKJC = DATA / "hkjc_current.csv"
FOREBET = DATA / "forebet_current.csv"
REGISTRY = DATA / "prediction_source_registry.csv"
OUT = DATA / "prediction_fallback_current.csv"
HKT = timezone(timedelta(hours=8))
UA = "football-fast-tracker-prediction-fallback/1.0"
TIMEOUT = 15
HORIZON_HOURS = 48

FIELDS = [
    "fetched_at_hkt","hkjc_event_id","kickoff_hkt","hkjc_league","home_en","away_en",
    "source","source_competition","source_url","recommendation","market","match_score",
    "status","notes"
]

def clean(v):
    return "" if v is None else str(v).strip()

def norm(v):
    s = unicodedata.normalize("NFKD", clean(v))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"['’`]", "", s)
    s = re.sub(r"\b(women|womens|woman|femenino|femenina|fem|res|reserve|fc|cf|sc|club)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())

def tokens(v):
    return {t for t in norm(v).split() if len(t) >= 3}

def slug_score(target_home, target_away, href):
    path = urlparse(href).path
    bag = tokens(path.replace("-", " "))
    ht, at = tokens(target_home), tokens(target_away)
    if not ht or not at:
        return 0.0
    hs = len(ht & bag) / len(ht)
    ats = len(at & bag) / len(at)
    return (hs + ats) / 2

def parse_dt(v):
    s = clean(v)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=HKT)
        return dt.astimezone(HKT)
    except Exception:
        try:
            serial = float(s)
            origin = datetime(1899, 12, 30, tzinfo=HKT)
            return origin + timedelta(days=serial)
        except Exception:
            return None

def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def forebet_covered_ids(rows):
    out = set()
    for r in rows:
        eid = clean(r.get("hkjc_event_id"))
        has_pick = any(clean(r.get(k)) for k in (
            "prediction_1x2","predicted_score","prediction_ou25","corner_prediction"
        ))
        if eid and has_pick:
            out.add(eid)
    return out

def load_registry(rows):
    reg = {}
    for r in rows:
        if clean(r.get("enabled")).lower() not in ("1","true","yes","y"):
            continue
        league = clean(r.get("hkjc_league")).upper()
        if league:
            reg[league] = r
    return reg

def textify(raw_html):
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw_html)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = html.unescape(text)
    text = re.sub(r"[\t\r ]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()

def get(url):
    r = requests.get(
        url,
        headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.text

def prediction_links(league_url):
    raw = get(league_url)
    hrefs = re.findall(r"""(?i)href=["']([^"']+/predictions/[^"'#?]+)["']""", raw)
    return sorted({urljoin(league_url, h) for h in hrefs if "-prediction-" in h})

def pick_link(target, links):
    kick = target["kickoff_hkt"]
    date_suffix = kick.strftime("%d-%m-%Y")
    ranked = []
    for href in links:
        if re.search(r"\d{2}-\d{2}-\d{4}", href) and date_suffix not in href:
            continue
        score = slug_score(target["home_en"], target["away_en"], href)
        if score >= 0.45:
            ranked.append((score, href))
    ranked.sort(reverse=True)
    if not ranked:
        return "", 0.0
    if len(ranked) > 1 and ranked[0][0] < 0.85 and ranked[0][0] - ranked[1][0] < 0.15:
        return "", ranked[0][0]
    return ranked[0][1], ranked[0][0]

def parse_apwin_page(url):
    raw = get(url)
    text = textify(raw)
    rec = ""
    m = re.search(r"(?is)Our prediction is:\s*([^\n]{2,120})", text)
    if m:
        rec = clean(m.group(1))
    market = ""
    m2 = re.search(r"(?is)APWin Prediction\s*\n\s*([^\n]{2,120})", text)
    if m2:
        market = clean(m2.group(1))
    if not rec and market:
        rec = market
    if not market and rec:
        market = "APWIN_MAIN"
    return rec, market

def main():
    now = datetime.now(HKT)
    fetched = now.isoformat(timespec="seconds")
    hkjc = read_csv(HKJC)
    forebet = read_csv(FOREBET) if FOREBET.exists() else []
    registry = load_registry(read_csv(REGISTRY))
    covered = forebet_covered_ids(forebet)

    targets = []
    for r in hkjc:
        eid = clean(r.get("hkjc_event_id"))
        if not eid or eid in covered:
            continue
        kick = parse_dt(r.get("kickoff_hkt"))
        if not kick or not (now - timedelta(hours=2) <= kick <= now + timedelta(hours=HORIZON_HOURS)):
            continue
        status = clean(r.get("status")).upper()
        if any(x in status for x in ("ENDED","VOID","CANCEL","ABANDON","FT")):
            continue
        targets.append({
            "hkjc_event_id":eid,
            "kickoff_hkt":kick,
            "hkjc_league":clean(r.get("tournament")).upper(),
            "home_en":clean(r.get("home_en")),
            "away_en":clean(r.get("away_en")),
        })

    links_cache = {}
    rows = []
    for t in targets:
        reg = registry.get(t["hkjc_league"])
        base = {
            "fetched_at_hkt":fetched,
            "hkjc_event_id":t["hkjc_event_id"],
            "kickoff_hkt":t["kickoff_hkt"].isoformat(timespec="minutes"),
            "hkjc_league":t["hkjc_league"],
            "home_en":t["home_en"],
            "away_en":t["away_en"],
            "source":"APWIN",
            "source_competition":"",
            "source_url":"",
            "recommendation":"",
            "market":"",
            "match_score":"",
            "status":"",
            "notes":"",
        }
        if not reg:
            base["status"] = "NO_APWIN_MAPPING"
            base["notes"] = "Add league mapping in prediction_source_registry.csv"
            rows.append(base)
            continue

        league_url = clean(reg.get("source_url"))
        base["source_competition"] = clean(reg.get("source_competition"))
        if not league_url:
            base["status"] = "NO_APWIN_URL"
            rows.append(base)
            continue

        try:
            if league_url not in links_cache:
                links_cache[league_url] = prediction_links(league_url)
            link, score = pick_link(t, links_cache[league_url])
            base["match_score"] = f"{score:.3f}"
            if not link:
                base["status"] = "NO_APWIN_MATCH"
                base["notes"] = "League page found, no confident match link"
                rows.append(base)
                continue
            rec, market = parse_apwin_page(link)
            base["source_url"] = link
            base["recommendation"] = rec
            base["market"] = market
            base["status"] = "OK" if rec else "NO_APWIN_RECOMMENDATION"
        except Exception as e:
            base["status"] = "ERROR_" + type(e).__name__
            base["notes"] = str(e)[:180]
        rows.append(base)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} fallback rows to {OUT}")

if __name__ == "__main__":
    main()
