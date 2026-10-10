#!/usr/bin/env python3
"""Bounded one-shot check of public Forebet pages from an ordinary GitHub runner.
Never uses proxies, CAPTCHA bypass, authentication, paid services or publishing.
"""
import json,urllib.request,urllib.error,sys
from html.parser import HTMLParser
from datetime import datetime,timezone
URLS={
 "dated_legacy":"https://www.forebet.com/en/football-predictions/predictions-1x2/2026-10-10",
 "home":"https://www.forebet.com/en/home-en",
 "today":"https://www.forebet.com/en/football-predictions?task=day",
 "top_europe":"https://www.forebet.com/en/prediction-lists/top-europe",
}
MAX_BODY=2000000
class SourceParser(HTMLParser):
 def __init__(self):
  super().__init__()
  self.matches=0
  self.rcnt=0
  self.datetimes=[]
  self.perc=0
  self.tags={}
 def handle_starttag(self,tag,attrs):
  a=dict(attrs);classes=(a.get("class") or "").split()
  if "rcnt" in classes:self.rcnt+=1
  if "fprc" in classes:self.perc+=1
  if tag=="time" and a.get("datetime"): self.datetimes.append(a["datetime"][:40])
  if tag=="meta" and a.get("itemprop")=="name" and " vs " in (a.get("content") or ""):
   self.matches+=1
  for word in ("homeTeam","awayTeam","forepr","avg_sc","predict_score","ex_sc"):
   if word in classes:self.tags[word]=self.tags.get(word,0)+1

def probe():
 results={}
 for key,url in URLS.items():
  try:
   req=urllib.request.Request(url,headers={"User-Agent":"FastTrackerPersonalForebetDiagnostic/1.0","Accept":"text/html"})
   with urllib.request.urlopen(req,timeout=12) as response:
    data=response.read(MAX_BODY+1)
    status=response.status
    lasturl=response.url
   if len(data)>MAX_BODY:raise ValueError("response exceeds 2 MB")
   page=data.decode("utf-8",errors="replace")
   ps=SourceParser();ps.feed(page)
   result={"http":status,"bytes":len(data),"rcnt":ps.rcnt,"row_metadata":ps.matches,
      "prob_containers":ps.perc,"tags":ps.tags,"time_nodes":len(ps.datetimes),
      "sample_time":ps.datetimes[:2],"html":'<html' in page.lower(),
      "access_challenge":any(k in page.lower() for k in ("cf-challenge","captcha","access denied")),
      "usable_candidate":ps.rcnt>=3 and ps.perc>=3 and ps.matches>=3,
      "redirected":lasturl!=url}
  except urllib.error.HTTPError as e:
   result={"http":e.code,"usable_candidate":False,"error":"HTTPError"}
  except (urllib.error.URLError,TimeoutError,ValueError) as e:
   result={"usable_candidate":False,"error":type(e).__name__,"detail":str(e)[:115]}
  results[key]=result
  print("FOREBET_OFFICIAL_PAGE "+key+" "+json.dumps(result,ensure_ascii=False),flush=True)
 print("FOREBET_SOURCE_CONCLUSION "+json.dumps({"accessible":[k for k,v in results.items() if v.get("usable_candidate")],
      "unavailable":[k for k,v in results.items() if not v.get("usable_candidate")]},ensure_ascii=False))
 return 0
if __name__=="__main__":sys.exit(probe())
