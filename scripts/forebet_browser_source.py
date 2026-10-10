"""One Forebet source page, one browser expand, only canonical candidate rows.

Uses the existing tested local browser-helper pattern, but never copies cookies,
HTML, challenges or screenshots into persistent artifacts. No broad pagination.
"""
from __future__ import annotations
import json
import requests
from playwright.sync_api import sync_playwright
from scrape_forebet import parse_forebet_rows
from forebet_verified_aliases import source_forms

def load_canonical_candidates(url: str, date: str, targets: list[dict],
                              helper="http://127.0.0.1:8191/v1"):
    request=requests.post(helper,json={"cmd":"request.get","url":url,"maxTimeout":55000},
                          timeout=65)
    request.raise_for_status()
    answer=request.json()
    sol=answer.get("solution") or {}
    page_html=sol.get("response") or ""
    if (answer.get("status")!="ok" or sol.get("status")!=200
        or not isinstance(page_html,str) or len(page_html.encode("utf-8"))>2_000_000
        or "rcnt" not in page_html):
        raise ValueError("FOREBET_PAGE_NOT_READABLE")
    ua=sol.get("userAgent")
    if not ua:raise ValueError("FOREBET_BROWSER_IDENTITY_ABSENT")
    cookies=[]
    for c in (sol.get("cookies") or [])[:20]:
        dom=str(c.get("domain") or "")
        if dom.lstrip(".") in ("forebet.com","www.forebet.com") and c.get("name") and c.get("value"):
            cookies.append({"name":str(c["name"]),"value":str(c["value"]),
                            "domain":dom,"path":str(c.get("path") or "/")})
    # Source-only, already verified alternative names. Build compact full pairs
    # before entering the browser; no alias queries and no extra network calls.
    allowed=set()
    for t in targets[:350]:
        home=source_forms(t["home"])
        away=source_forms(t["away"])
        for h in home:
            for a in away:
                allowed.add(h+"|"+a)
    if len(allowed)>15000:
        raise ValueError("FOREBET_ALIAS_ALLOWLIST_TOO_LARGE")
    pairs=sorted(allowed)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(user_agent=str(ua),locale="en-GB")
        if cookies:context.add_cookies(cookies)
        page=context.new_page()
        response=page.goto(url,wait_until="domcontentloaded",timeout=25_000)
        if not response or response.status!=200:
            raise ValueError("FOREBET_BROWSER_PAGE_REJECTED")
        page.wait_for_timeout(1600)
        initial=page.locator("div.rcnt").count()
        if initial<3:raise ValueError("FOREBET_NO_MATCH_ROWS")
        more=page.locator("#mrows span[onclick*='ltodrows']").first
        if more.count() and more.is_visible():
            more.click(timeout=3000)
            try:
                page.wait_for_function("document.querySelectorAll('div.rcnt').length > 100",
                                       timeout=10000)
            except Exception:
                pass
        result=page.evaluate("""allowedPairs=>{
           const norm=s=>String(s||'').normalize('NFKD').toLowerCase().replace(/[^a-z0-9]/g,'');
           const allowed=new Set(allowedPairs);
           let total=0,size=0;
           const fragments=[];
           const all=document.querySelectorAll('div.rcnt');
           for(const row of all) {
             const home=(row.querySelector('span.homeTeam span[itemprop="name"]') ||
                         row.querySelector('span.homeTeam'))?.textContent?.trim();
             const away=(row.querySelector('span.awayTeam span[itemprop="name"]') ||
                         row.querySelector('span.awayTeam'))?.textContent?.trim();
             if(!allowed.has(norm(home)+'|'+norm(away))) continue;
             total++;
             const fragment=row.outerHTML;
             if(fragments.length<80 && size+fragment.length<1150000){
                 fragments.push(fragment);size+=fragment.length;
             }
           }
           return {all:all.length,matching:total,fragments};
        }""",pairs)
        browser.close()
    if result["all"]>1500 or result["matching"]>80:
        raise ValueError("FOREBET_PROVIDER_OVERSIZE")
    html="<html><body>"+"".join(result["fragments"])+"</body></html>"
    rows=parse_forebet_rows(html,date)
    return rows,{"initial":initial,"expanded":result["all"],
                 "matched":result["matching"],"parsed_candidates":len(rows)}
