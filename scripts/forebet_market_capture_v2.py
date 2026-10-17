"""Optional bounded Forebet U/O 2.5 and corners 9.5 source capture.

Run inside the EXISTING daily 1X2 job only, never as another scheduler.
The two market pages have their own models; goal averages are not used to
invent corner totals or market probabilities. A market must have a unique,
identical Forebet event URL, oriented names, league and minute kickoff.
"""
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from forebet_canonical_source_probe import exact_name
from capture_forebet_canonical_light import displayed_wall_clock

EVENT = re.compile(r"^https://www[.]forebet[.]com/en/football/matches/[^/?#]+-[0-9]{5,12}/?$")
SCORE = re.compile(r"^([0-9]{1,2})\\s*-\\s*([0-9]{1,2})$")
AVG = re.compile(r"^[0-9]{1,2}(?:\\.[0-9]{1,3})?$")
MAX_MARKET_PAGES = 6

def _text(row, selector):
    tag = row.select_one(selector)
    return tag.get_text(" ",strip=True) if tag else ""

def _source_url(row):
    link = row.find("a",href=re.compile(r"/(?:en/)?football/matches/",re.I))
    uri = urljoin("https://www.forebet.com",str(link.get("href"))) if link else ""
    uri = uri.split("?")[0].split("#")[0].rstrip("/")
    return uri if EVENT.fullmatch(uri) else ""

def parse_market_rows(html, date, market):
    """Parse *only* complete row-local DOM evidence, never neighboring rows."""
    if market not in {"ou25","corners95"}:
        raise ValueError("INVALID_FOREBET_MARKET")
    soup = BeautifulSoup(html,"lxml")
    from scrape_forebet import normalize_date
    rows=[]
    for r in soup.select("div.rcnt"):
        home = _text(r,'span.homeTeam span[itemprop="name"]') or _text(r,"span.homeTeam")
        away = _text(r,'span.awayTeam span[itemprop="name"]') or _text(r,"span.awayTeam")
        link = _source_url(r)
        if not home or not away or not link: continue
        nums = [p.get_text(" ",strip=True).replace("%","") for p in r.select("div.fprc span")]
        if len(nums)!=2 or any(not x.isdigit() for x in nums): continue
        under, over = [int(x) for x in nums]
        if not 0<=under<=100 or not 0<=over<=100 or not 98<=under+over<=102: continue
        pred_text = _text(r,"span.forepr span") or _text(r,".forepr")
        pick_match = re.search(r"\\b(Under|Over)\\b",pred_text,re.I)
        if not pick_match: continue
        pick = pick_match.group(1).capitalize()
        score_txt = _text(r,"div.ex_sc.tabonly") or _text(r,".predict_score, .ex_sc")
        score_match = SCORE.fullmatch(score_txt.strip())
        if market=="corners95" and not score_match: continue
        avg_txt = _text(r,"div.avg_sc.tabonly") or _text(r,".avg_sc")
        if avg_txt and not AVG.fullmatch(avg_txt): continue
        time = r.find("time")
        row={
            "home_team":home,"away_team":away,
            "league_short":_text(r,"span.shortTag"),
            "match_date":normalize_date(str(time.get("datetime") or "") if time else "",date),
            "kickoff_text":_text(r,"span.date_bah"),
            "forebet_detail_url":link,
            "market":market,
            "prediction":pick,
            "under":under,
            "over":over
        }
        if score_match:
            row["predicted_score"] = score_match.group(1)+" - "+score_match.group(2)
        if avg_txt:
            avg=float(avg_txt)
            if 0<=avg<=30: row["average"]=avg
            else: continue
        if displayed_wall_clock(row) is None: continue
        rows.append(row)
    return rows

def parse_ou25(html,date):
    return parse_market_rows(html,date,"ou25")

def parse_corners95(html,date):
    return parse_market_rows(html,date,"corners95")

def enrich_verified_rows(verified, market_rows):
    """Attach optional source fields to VERIFIED 1X2 rows only.

    Ambiguity within any market leaves that market unknown. Comparing event
    URL alone is not sufficient: oriented names, league and visible UTC clock
    must also match the original 1X2 observation.
    """
    index=defaultdict(list)
    for r in market_rows:
        if r.get("market") in {"ou25","corners95"} and EVENT.fullmatch(str(r.get("forebet_detail_url") or "")):
            index[(r["market"],r["forebet_detail_url"])].append(r)
    coverage={"ou25":0,"corners95":0,"ambiguous":0}
    for original in verified:
        source_url=str(original.get("source_event_url") or "").rstrip("/")
        if not EVENT.fullmatch(source_url): continue
        original_names=(exact_name(original.get("source_home")),exact_name(original.get("source_away")))
        original_league=str(original.get("source_league") or "")
        original_clock=str(original.get("source_event_time") or "")
        for market in ("ou25","corners95"):
            candidates=[]
            for row in index.get((market,source_url),[]):
                clock=displayed_wall_clock(row)
                if (exact_name(row.get("home_team")),exact_name(row.get("away_team")))!=original_names:
                    continue
                if str(row.get("league_short") or "")!=original_league: continue
                # The V2 contract calibrates Forebet's complete displayed clock to UTC.
                if not clock or clock.isoformat()+"+00:00"!=original_clock: continue
                candidates.append(row)
            unique={(
                r.get("prediction"),r.get("under"),r.get("over"),
                r.get("predicted_score"),r.get("average")
            ) for r in candidates}
            if len(unique)!=1:
                if len(unique)>1: coverage["ambiguous"]+=1
                continue
            r=candidates[0]
            original["forebet_detail_url"]=source_url
            if market=="ou25":
                original.update({
                    "prediction_ou25":r["prediction"],
                    "prob_under25":r["under"],"prob_over25":r["over"],
                })
                if r.get("predicted_score"): original["ou_predicted_score"]=r["predicted_score"]
            else:
                original.update({
                    "corner_prediction":r["prediction"],
                    "corner_prob_under95":r["under"],"corner_prob_over95":r["over"],
                    "corner_predicted_score":r["predicted_score"],
                })
                if r.get("average") is not None:
                    original["avg_corners"]=r["average"]
            coverage[market]+=1
    return coverage
