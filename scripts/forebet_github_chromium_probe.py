#!/usr/bin/env python3
"""Single normal Chromium probe; no stealth/proxy, no challenge solving or writes."""
from playwright.sync_api import sync_playwright,TimeoutError as PWTimeout
import json
URLS=[
 ("homepage","https://www.forebet.com/en/home-en"),
 ("today_1x2","https://www.forebet.com/en/football-predictions?task=day"),
]
def main():
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  context=browser.new_context(locale="en-GB",timezone_id="UTC")
  page=context.new_page()
  for label,url in URLS:
   try:
    response=page.goto(url,wait_until="domcontentloaded",timeout=22000)
    # A normal browser sometimes completes JavaScript initialization after
    # navigation; wait once, not a retry or challenge/CAPTCHA bypass.
    page.wait_for_timeout(8500 if response and response.status==403 else 1000)
    data=page.evaluate("""() => ({
       title: document.title.slice(0,110),
       rows: document.querySelectorAll('div.rcnt').length,
       home: document.querySelectorAll('span.homeTeam').length,
       away: document.querySelectorAll('span.awayTeam').length,
       probability: document.querySelectorAll('div.fprc').length,
       avg: document.querySelectorAll('div.avg_sc').length,
       datetimes: [...document.querySelectorAll('div.rcnt time[datetime]')].slice(0,3).map(n => n.getAttribute('datetime')),
       dates: [...document.querySelectorAll('div.rcnt .date_bah')].slice(0,3).map(n => n.textContent.trim().slice(0,60)),
       challenged: Boolean(document.querySelector('#challenge-running, .cf-challenge')) 
     })""")
    print("FOREBET_BROWSER_PROBE "+label+" "+json.dumps({"http":response.status if response else None,**data}),flush=True)
   except (PWTimeout,Exception) as error:
    print("FOREBET_BROWSER_PROBE "+label+" "+json.dumps({"error":type(error).__name__,"detail":str(error)[:155]}),flush=True)
  browser.close()
if __name__=="__main__":main()
