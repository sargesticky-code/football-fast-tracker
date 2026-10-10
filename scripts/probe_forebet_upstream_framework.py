#!/usr/bin/env python3
"""One-shot Forebet upstream-framework proof, never published or scheduled.

Adaptation of the *architecture* (GitHub Actions browser service + one page +
existing Forebet parser) described at Alm77ar/Forebet-Scraper, without copying
that repository's unlicensed source, Telegram code, cookies or credentials.
External service has no public ingress; all artifacts remain run-scoped.
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from scrape_forebet import parse_forebet_rows

HKT = timezone(timedelta(hours=8))
SOLVER = os.environ.get("LOCAL_BROWSER_HELPER", "http://127.0.0.1:8191/v1")
OUT = Path("/tmp/ft-forebet-upstream-proof.json")
ALLOWED_HOST = "www.forebet.com"
MAX_BODY = 2_000_000

def fmt(row):
    fields = ("home_team","away_team","prob_home","prob_draw","prob_away",
              "prediction_1x2","predicted_score","avg_goals",
              "source_kickoff_iso","forebet_detail_url")
    return {k:row.get(k) for k in fields}

def candidate_model(row):
    try:
        values=[float(row[k]) for k in ("prob_home","prob_draw","prob_away")]
        avg=float(row["avg_goals"])
    except (TypeError,ValueError,KeyError):
        return False
    return (all(0 <= p <= 100 for p in values)
       and 98 <= sum(values) <= 102 and 0 < avg <= 12
       and str(row.get("prediction_1x2") or "").strip() in ("1","X","2")
       and bool(re.fullmatch(r"\d{1,2}\s*-\s*\d{1,2}",
                             str(row.get("predicted_score") or "").strip())))

def run():
    hkt=datetime.now(HKT)
    # Precisely one official page per trial, no retries.
    date=hkt.strftime("%Y-%m-%d")
    url="https://"+ALLOWED_HOST+"/en/football-predictions/predictions-1x2/"+date
    payload={"cmd":"request.get","url":url,"maxTimeout":55000}
    try:
        resp=requests.post(SOLVER,json=payload,timeout=65,
                           headers={"Content-Type":"application/json"})
        resp.raise_for_status()
        result=resp.json()
    except (requests.RequestException,ValueError) as exc:
        print("FOREBET_FRAMEWORK_TEST "+json.dumps({"helper":"UNAVAILABLE","error":type(exc).__name__,
          "detail":str(exc)[:150],"source_url":url}),flush=True)
        return 2
    solution=result.get("solution") or {}
    html=solution.get("response") or ""
    status=solution.get("status")
    browser_status=result.get("status")
    if not isinstance(html,str) or len(html.encode("utf-8"))>MAX_BODY:
        print("FOREBET_FRAMEWORK_TEST "+json.dumps({"helper":browser_status,
          "status":status,"reason":"empty or oversize HTML","source_url":url}),flush=True)
        return 3
    # Evidence belongs to this source. No browser session tokens/cookies logged.
    challenge=any(s in html.lower() for s in ("just a moment","cf-challenge","checking your browser","access denied"))
    rows=parse_forebet_rows(html,date) if html else []
    valid=[fmt(x) for x in rows if candidate_model(x)]
    # Diagnostics for the actual rendered source clock, without guessing UTC.
    from bs4 import BeautifulSoup
    dom=BeautifulSoup(html,"lxml")
    samples=[]
    for tag in dom.select("div.rcnt")[:10]:
        node=tag.select_one("time")
        dt=(node.get("datetime") if node else None)
        date_elem=tag.select_one("span.date_bah")
        tag_text=date_elem.get_text(" ",strip=True) if date_elem else ""
        team_h=tag.select_one("span.homeTeam")
        team_a=tag.select_one("span.awayTeam")
        samples.append({"home":team_h.get_text(" ",strip=True)[:55] if team_h else None,
                        "away":team_a.get_text(" ",strip=True)[:55] if team_a else None,
                        "datetime_attr":dt,"time_attrs":dict(node.attrs) if node else {},
                        "visible_date":tag_text[:90],
                        "league":(tag.select_one("span.shortTag").get_text(" ",strip=True)
                                  if tag.select_one("span.shortTag") else "")})
    print("FOREBET_ACTUAL_TIME_SHAPE "+json.dumps({
       "time_node_count":len(dom.select("div.rcnt time")),
       "datetime_populated":sum(1 for n in dom.select("div.rcnt time") if n.get("datetime")),
       "date_text_nodes":len(dom.select("div.rcnt span.date_bah")),
       "samples":samples},ensure_ascii=False),flush=True)

    proof={"source_url":url,"requested_at":hkt.isoformat(),"helper_status":browser_status,
           "http":status,"bytes":len(html.encode("utf-8")),
           "page_has_rows":"rcnt" in html,"challenge_html":challenge,
           "parsed_rows":len(rows),"valid_model_shapes":len(valid),
           "source_time_explicit":sum(bool(x.get("source_kickoff_iso")) for x in valid),
           "sample":valid[:3],"published":False,"scheduled":False}
    OUT.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding="utf-8")
    print("FOREBET_FRAMEWORK_TEST "+json.dumps(proof,ensure_ascii=False),flush=True)
    return 0 if valid else 3

if __name__=="__main__":
    raise SystemExit(run())
