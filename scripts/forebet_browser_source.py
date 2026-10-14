"""Bounded Forebet source-page capture with complete-page parsing when feasible.

Fetch once through existing browser helper, expand once, then parse rows locally.
No source HTML, cookies, browser storage, or unmatched fixture names persisted.
If a site's rendered HTML exceeds the budget, fall back to the known-pair
allowlist (recorded explicitly in proof, never silently claim full coverage).
"""
from __future__ import annotations

import requests
from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeoutError
from scrape_forebet import parse_forebet_rows
from forebet_verified_aliases import source_forms

MAX_SOURCE_BYTES = 2_000_000
MAX_RENDERED_ROWS = 1800
MAX_RENDERED_HTML = 6_000_000
MAX_ALLOWED_PAIR_ROWS = 300


def load_canonical_candidates(url: str, date: str, targets: list[dict],
                              helper="http://127.0.0.1:8191/v1"):
    # Same single helper request per date as V2. No page retries/pagination.
    request = requests.post(helper, json={
        "cmd": "request.get", "url": url, "maxTimeout": 55000
    }, timeout=65)
    request.raise_for_status()
    answer = request.json()
    sol = answer.get("solution") or {}
    page_html = sol.get("response") or ""
    if (answer.get("status") != "ok" or sol.get("status") != 200
            or not isinstance(page_html, str)
            or len(page_html.encode("utf-8")) > MAX_SOURCE_BYTES
            or "rcnt" not in page_html):
        raise ValueError("FOREBET_PAGE_NOT_READABLE")
    ua = sol.get("userAgent")
    if not ua:
        raise ValueError("FOREBET_BROWSER_IDENTITY_ABSENT")
    cookies = []
    for c in (sol.get("cookies") or [])[:20]:
        dom = str(c.get("domain") or "")
        if (dom.lstrip(".") in ("forebet.com", "www.forebet.com")
                and c.get("name") and c.get("value")):
            cookies.append({
                "name": str(c["name"]), "value": str(c["value"]),
                "domain": dom, "path": str(c.get("path") or "/")
            })
    allowed = set()
    for target in targets[:350]:
        for home in source_forms(target["home"]):
            for away in source_forms(target["away"]):
                allowed.add(home + "|" + away)
    if len(allowed) > 15000:
        raise ValueError("FOREBET_ALIAS_ALLOWLIST_TOO_LARGE")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=str(ua), locale="en-GB")
            if cookies:
                context.add_cookies(cookies)
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=35000)
            if not response or response.status != 200:
                raise ValueError("FOREBET_BROWSER_PAGE_REJECTED")
            page.wait_for_timeout(1200)
            initial = page.locator("div.rcnt").count()
            if initial < 3:
                raise ValueError("FOREBET_NO_MATCH_ROWS")
            more = page.locator("#mrows span[onclick*='ltodrows']").first
            expanded = False
            if more.count() and more.is_visible():
                more.click(timeout=3000)
                expanded = True
                # > 100 was an incorrect condition when initial >= 100.
                # Wait for a real increase; at most one click, never loop.
                try:
                    page.wait_for_function(
                        "(before) => document.querySelectorAll('div.rcnt').length > before",
                        arg=initial, timeout=18000)
                    page.wait_for_timeout(700)
                except BrowserTimeoutError as exc:
                    # Clicking a visible "more" control without new rows is
                    # incomplete coverage, NOT a successful full-page capture.
                    raise ValueError("FOREBET_EXPANSION_UNVERIFIED") from exc
            result = page.evaluate("""({allowedPairs,maxRows,maxBytes,maxMatches})=>{
              const norm=s=>String(s||'').normalize('NFKD').toLowerCase()
                .replace(/[^a-z0-9]/g,'');
              const allowed=new Set(allowedPairs);
              const all=document.querySelectorAll('div.rcnt');
              if(all.length>maxRows) return {oversize:true,all:all.length};
              let matching=0, bytes=0, matchedBytes=0;
              const full=[], matched=[];
              for(const row of all){
                const home=(row.querySelector('span.homeTeam span[itemprop="name"]') ||
                  row.querySelector('span.homeTeam'))?.textContent?.trim();
                const away=(row.querySelector('span.awayTeam span[itemprop="name"]') ||
                  row.querySelector('span.awayTeam'))?.textContent?.trim();
                const ok=allowed.has(norm(home)+'|'+norm(away));
                const fragment=row.outerHTML;
                const n=new TextEncoder().encode(fragment).length;
                bytes+=n;
                if(ok){
                  matching++;
                  matchedBytes+=n;
                  if(matching<=maxMatches) matched.push(fragment);
                }
                if(bytes<=maxBytes) full.push(fragment);
              }
              if(matching>maxMatches || matchedBytes>maxBytes)
                return {oversize:true,all:all.length,matching};
              const complete=bytes<=maxBytes;
              return {all:all.length,matching,bytes,
                mode:complete?'full_page':'allowlist_fallback',
                fragments:complete?full:matched};
            }""", {
                "allowedPairs": sorted(allowed),
                "maxRows": MAX_RENDERED_ROWS,
                "maxBytes": MAX_RENDERED_HTML,
                "maxMatches": MAX_ALLOWED_PAIR_ROWS
            })
        finally:
            browser.close()
    if result.get("oversize"):
        raise ValueError("FOREBET_RENDERED_PAGE_OVER_LIMIT")
    html = "<html><body>" + "".join(result["fragments"]) + "</body></html>"
    rows = parse_forebet_rows(html, date)
    return rows, {
        "initial": initial, "expanded": result["all"],
        "expand_clicked": expanded,
        "matched": result["matching"],
        "parsed_candidates": len(rows),
        "capture_mode": result["mode"],
        "rendered_html_bytes": result["bytes"],
    }
