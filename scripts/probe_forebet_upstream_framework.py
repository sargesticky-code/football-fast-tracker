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

def expand_with_normal_browser(url, solution, date):
    """Reuse the valid source session in a regular Chromium, then bounded scroll."""
    from playwright.sync_api import sync_playwright
    ua=solution.get("userAgent")
    cookies=solution.get("cookies") or []
    if not ua or not isinstance(cookies,list):
        return [], {"reason":"helper has no reusable browser session"}
    safe=[]
    for c in cookies[:20]:
        domain=str(c.get("domain") or "")
        if domain.lstrip(".") not in ("forebet.com","www.forebet.com"):
            continue
        if not c.get("name") or not c.get("value"):
            continue
        safe.append({"name":str(c["name"]),"value":str(c["value"]),
                     "domain":domain,"path":str(c.get("path") or "/")})
    outcome={"cookie_count_not_logged":True}
    pairs=[]
    try:
        api="https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/app-phase1-feed?view=summary&hours=48"
        canonical=requests.get(api,timeout=15).json()
        if canonical.get("source")=="flashscore-single-rpc-canonical":
            pairs=[{"home":m.get("home"),"away":m.get("away")} for m in canonical.get("matches",[])
                   if isinstance(m,dict) and m.get("home") and m.get("away")][:350]
        outcome["canonical_fixtures_available"]=len(pairs)
    except (requests.RequestException,ValueError) as error:
        outcome["canonical_error"]=type(error).__name__
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            context=browser.new_context(user_agent=str(ua),locale="en-GB")
            if safe:
                context.add_cookies(safe)
            page=context.new_page()
            response=page.goto(url,wait_until="domcontentloaded",timeout=25_000)
            # Give the public page's own list-expansion JS time to initialize.
            page.wait_for_timeout(1800)
            first=page.locator("div.rcnt").count()
            outcome.update({"http":response.status if response else None,"initial_rows":first})
            tz=page.locator("select.tzSel")
            if tz.count():
                outcome["timezone_control"]=tz.first.evaluate(
                    """e=>({value:e.value,
                     selectedText:e.selectedOptions.length?e.selectedOptions[0].textContent.trim().slice(0,55):null,
                     options:[...e.options].slice(0,8).map(o=>({v:o.value,t:o.textContent.trim().slice(0,25)}))})""")
            # Structural UI metadata only, no site cookies or auth values.
            tzloc=page.locator(".tzSel, .timezoneSelected").first
            if tzloc.count():
                outcome["timezone_widget"]=tzloc.evaluate(
                    """e=>({tag:e.tagName,text:(e.innerText||e.textContent||'').trim().slice(0,110),
                       cls:e.className,attrs:[...e.attributes].filter(x=>!(/token|csrf|session/i).test(x.name)).map(x=>[x.name,x.value.slice(0,90)])})""")
            outcome["load_more_controls"]=page.evaluate(
                """()=>Object.fromEntries(
                   ['#btn_more','.schema-more','#mrows span','span[onclick*="ltodrows"]','.more_rows','button[id*="more"]']
                   .map(s=>[s,document.querySelectorAll(s).length]))""")
            outcome["more_js_initialized"]=page.evaluate("typeof ltodrows === 'function'")
            outcome["more_control_visible"]=page.locator("#mrows span").first.is_visible() if page.locator("#mrows span").count() else False
            stagnant=0
            for step in range(8):
                old=page.locator("div.rcnt").count()
                more=page.locator("#btn_more, .schema-more, #mrows span, span[onclick*=\'ltodrows\']").first
                if more.count() and more.is_visible():
                    more.click(timeout=2000)
                else:
                    page.mouse.wheel(0,1500)
                page.wait_for_timeout(1800 if more.count() and more.is_visible() else 900)
                new=page.locator("div.rcnt").count()
                stagnant=stagnant+1 if new<=old else 0
                if stagnant>=3 or new>=200: break
            # A real MORE click exposes >1000 rows and many MB. Extract only
            # exact home/away pair candidates for existing canonical fixtures.
            selected=page.evaluate("""targets=>{
                 const norm=s=>String(s||'').normalize('NFKD').toLowerCase().replace(/[^a-z0-9]/g,'');
                 const keys=new Set(targets.map(t=>norm(t.home)+'|'+norm(t.away)));
                 const picked=[],counts={};let total=0,size=0;
                 for(const r of document.querySelectorAll('div.rcnt')){
                   const league=(r.querySelector('span.shortTag')?.textContent||'').trim();
                   counts[league]=(counts[league]||0)+1;
                   const home=(r.querySelector('span.homeTeam span[itemprop="name"]')||r.querySelector('span.homeTeam'))?.textContent?.trim();
                   const away=(r.querySelector('span.awayTeam span[itemprop="name"]')||r.querySelector('span.awayTeam'))?.textContent?.trim();
                   if(!keys.has(norm(home)+'|'+norm(away)))continue;
                   total++;
                   const part=r.outerHTML;
                   if(picked.length<80 && size+part.length<1200000){
                     picked.push(part);size+=part.length;
                   }
                 }
                 return {total:total,picked:picked,
                    leagues:Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,12)};
            }""",pairs)
            outcome["expanded_rows"]=page.locator("div.rcnt").count()
            outcome["source_league_counts_sample"]=selected["leagues"]
            outcome["canonical_name_pair_candidates"]=selected["total"]
            outcome["selected_canonical_candidate_rows"]=len(selected["picked"])
            html="<html><body>"+"".join(selected["picked"])+"</body></html>"
            browser.close()
        if len(html.encode("utf-8"))>MAX_BODY:
            outcome["reason"]="expanded HTML exceeded 2MB"
            return [],outcome
        return parse_forebet_rows(html,date),outcome
    except Exception as error:
        outcome["error"]=type(error).__name__
        outcome["detail"]=str(error)[:140]
        return [],outcome


def run():
    hkt=datetime.now(HKT)
    # Precisely one official page per trial, no retries.
    day_offset=int(os.environ.get("FOREBET_DAY_OFFSET","0"))
    if day_offset not in (0,1):
        raise ValueError("only today/tomorrow one-shot capture permitted")
    date=(hkt+timedelta(days=day_offset)).strftime("%Y-%m-%d")
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
    if os.environ.get("FOREBET_NORMAL_BROWSER","0")=="1" and rows:
        expanded,browser_info=expand_with_normal_browser(url,solution,date)
        print("FOREBET_BROWSER_EXPANSION "+json.dumps(browser_info,ensure_ascii=False),flush=True)
        if expanded:
            print("FOREBET_CANONICAL_SOURCE_CANDIDATES "+json.dumps({
                "source_models":sum(candidate_model(x) for x in expanded),
                "source_rows":len(expanded),
                "sample":[fmt(x) for x in expanded if candidate_model(x)][:5],
                "canonical_id_verified":False,
                "published":False},ensure_ascii=False),flush=True)

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
    timezones=[]
    for el in dom.select("select"):
        name=(el.get("id") or "")+" "+(el.get("name") or "")+" "+(el.get("class") or [""])[0]
        if any(x in name.lower() for x in ("time","zone","tz","offset")):
            selected=el.select_one("option[selected]")
            timezones.append({"select_name":name[:90],"selected":(selected.get_text(" ",strip=True)[:55]
                              if selected else None),"value":(selected.get("value") if selected else None)})
    print("FOREBET_TIMEZONE_CONTROL "+json.dumps({"selections":timezones,
       "gmt_in_html":bool(re.search(r"\bGMT\b",html)),
       "utc_in_html":bool(re.search(r"\bUTC\b",html)),
       "site_timezone_option_count":len(dom.select("select option"))},ensure_ascii=False),flush=True)
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
