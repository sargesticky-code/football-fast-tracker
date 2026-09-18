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
UA = "football-fast-tracker-apwin/1.1"
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

def prediction_links(page_url):
    raw = get(page_url)
    hrefs = re.findall(r"""(?i)href=["']([^"']+/predictions/[^"'#?]+)["']""", raw)
    return sorted({urljoin(page_url, h) for h in hrefs if "-prediction-" in h})

def global_prediction_links():
    pages = [
        "https://www.apwin.com/predictions/",
        "https://www.apwin.com/predictions/denmark/",
        "https://www.apwin.com/predictions/argentina/",
    ]
    links = set()
    for page in pages:
        try:
            links.update(prediction_links(page))
        except Exception:
            pass
    return sorted(links)

def pick_link(target, links):
    kick = target["kickoff_hkt"]
    date_suffixes = {
        (kick + timedelta(days=delta)).strftime("%d-%m-%Y")
        for delta in (-1, 0, 1)
    }
    ranked = []
    for href in links:
        if re.search(r"\d{2}-\d{2}-\d{4}", href) and not any(s in href for s in date_suffixes):
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
    registry = load_registry(read_csv(REGISTRY))
    previous_rows = read_csv(OUT) if OUT.exists() else []
    previous_good = {
        clean(r.get("hkjc_event_id")): r
        for r in previous_rows
        if clean(r.get("hkjc_event_id")) and clean(r.get("recommendation"))
    }
    global_links = global_prediction_links()

    targets = []
    for r in hkjc:
        eid = clean(r.get("hkjc_event_id"))
        if not eid:
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
        try:
            # First try the broad APWin prediction indexes so APWin remains a
            # true second opinion even when Forebet already has a model.
            link, score = pick_link(t, global_links)

            # If the broad indexes do not expose the match, fall back to an
            # optional permanent league mapping.
            if not link and reg:
                league_url = clean(reg.get("source_url"))
                base["source_competition"] = clean(reg.get("source_competition"))
                if league_url:
                    if league_url not in links_cache:
                        links_cache[league_url] = prediction_links(league_url)
                    link, score = pick_link(t, links_cache[league_url])

            base["match_score"] = f"{score:.3f}"
            if not link:
                base["status"] = "NO_APWIN_MATCH"
                base["notes"] = "No confident match link on global or mapped APWin pages"
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

        if not clean(base.get("recommendation")):
            old = previous_good.get(base["hkjc_event_id"])
            if old:
                for key in ("source_competition","source_url","recommendation","market","match_score"):
                    if clean(old.get(key)):
                        base[key] = clean(old.get(key))
                base["status"] = "LAST_GOOD"
                base["notes"] = "Current refresh found no advice; retained previous valid APWin recommendation"

        rows.append(base)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} APWin rows to {OUT}; global_links={len(global_links)}")

if __name__ == "__main__":
    main()
