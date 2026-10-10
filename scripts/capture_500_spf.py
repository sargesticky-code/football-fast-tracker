#!/usr/bin/env python3
"""Read-only official 500.com SPF H/D/A capture. Never guesses fixture IDs.

Source: trade.500.com public jczq HTML + public pl_spf_2.xml, exact same
matchnum + xml event id, independently matched to existing canonical fixtures.
No oddsportal, HKJC, new alias database, or third-party cached prices.
"""
from __future__ import annotations
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

HKT = timezone(timedelta(hours=8))
XML_URL = "https://trade.500.com/static/public/jczq/newxml/pl/pl_spf_2.xml"
INDEX_URL = "https://trade.500.com/jczq/?playid=269&g=2"
FIXTURES_URL = "https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/app-phase1-feed?view=summary&hours=48"
OUTPUT = Path("/tmp/ft500-spf-canonical.json")
# Explicitly reviewed Chinese Simplified -> canonical English names. Do NOT infer
# absent names or rely on kickoff alone to identify same-time matches.
EPL_NAMES = {
    "阿森纳":"Arsenal","利兹联":"Leeds","伊普斯维奇":"Ipswich",
    "富勒姆":"Fulham","切尔西":"Chelsea","伯恩茅斯":"Bournemouth",
    "阿斯顿维拉":"Aston Villa","布伦特福德":"Brentford",
    "曼彻斯特联":"Manchester Utd","托特纳姆热刺":"Tottenham",
    "水晶宫":"Crystal Palace","诺丁汉森林":"Nottingham Forest",
    "赫尔城":"Hull City","埃弗顿":"Everton","利物浦":"Liverpool",
    "曼彻斯特城":"Manchester City","考文垂":"Coventry",
    "纽卡斯尔联":"Newcastle","桑德兰":"Sunderland","布莱顿":"Brighton"
}

# Pairs checked against the actual provider HTML/XML and current canonical
# fixtures on 2026-10-10. No fuzzy translation or time-only join.
VERIFIED_LEAGUES = {
    "英格兰超级联赛": ("EPL", EPL_NAMES),
    "西班牙甲级联赛": ("LaLigaSPAIN:", {
        "巴列卡诺":"Rayo Vallecano","毕尔巴鄂竞技":"Ath. Bilbao",
        "阿拉维斯":"Alaves","马德里竞技":"Atl. Madrid",
        "巴塞罗那":"Barcelona","赫塔费":"Getafe",
        "皇家马德里":"Real Madrid","比利亚雷亚尔":"Villarreal",
        "埃尔切":"Elche","维戈塞尔塔":"Celta Vigo",
        "皇家社会":"Real Sociedad","拉科鲁尼亚":"A Coruna",
        "皇家贝蒂斯":"Betis","奥萨苏纳":"Osasuna",
        "桑坦德竞技":"Racing Santander","巴伦西亚":"Valencia"
    }),
    "意大利甲级联赛": ("Serie AITALY:", {
        "热那亚":"Genoa","佛罗伦萨":"Fiorentina",
        "国际米兰":"Inter","帕尔马":"Parma",
        "那不勒斯":"Napoli","弗洛西诺内":"Frosinone",
        "科莫":"Como","罗马":"AS Roma",
        "拉齐奥":"Lazio","蒙扎":"Monza",
        "莱切":"Lecce","博洛尼亚":"Bologna",
        "萨索洛":"Sassuolo","AC米兰":"AC Milan",
        "卡利亚里":"Cagliari","尤文图斯":"Juventus"
    }),
    "德国甲级联赛": ("BundesligaGERMANY:", {
        "柏林联合":"Union Berlin","埃尔沃斯堡":"Elversberg",
        "奥格斯堡":"Augsburg","拜仁慕尼黑":"Bayern",
        "美因茨":"Mainz","勒沃库森":"Leverkusen",
        "帕德博恩":"Paderborn","斯图加特":"Stuttgart",
        "霍芬海姆":"Hoffenheim","汉堡":"Hamburger SV",
        "莱比锡红牛":"RB Leipzig","法兰克福":"Frankfurt",
        "科隆":"FC Koln","门兴格拉德巴赫":"Monchengladbach",
        "弗赖堡":"Freiburg","沙尔克04":"Schalke"
    }),
    "法国甲级联赛": ("Ligue 1FRANCE:", {
        "里尔":"Lille","勒阿弗尔":"Le Havre",
        "摩纳哥":"Monaco","图卢兹":"Toulouse",
        "尼斯":"Nice","斯特拉斯堡":"Strasbourg",
        "特鲁瓦":"Troyes","马赛":"Marseille"
    })
}

def verified_canonical_league(source_league, canonical_league):
    config=VERIFIED_LEAGUES.get(source_league)
    if not config or not isinstance(canonical_league,str):
        return False
    prefix=config[0]
    return canonical_league==prefix if prefix=="EPL" else canonical_league.startswith(prefix)

class MatchIndex(HTMLParser):
    def __init__(self):
        super().__init__()
        self.matches = {}
        self.duplicates = set()
    def handle_starttag(self, tag, attrs):
        if tag != "tr":
            return
        row = dict(attrs)
        number = row.get("data-processname")
        if not number or not row.get("data-matchdate") or not row.get("data-matchtime"):
            return
        if number in self.matches:
            self.duplicates.add(number)
        else:
            self.matches[number] = row

def iso_time(raw):
    if not isinstance(raw,str) or not raw.strip():
        return None
    try:
        result=datetime.fromisoformat(raw.replace("Z","+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError:
        return None

def norm(s):
    return "".join(c.casefold() for c in str(s or "") if c.isalnum())

def to_utc_china(s):
    try:
        return datetime.fromisoformat(s).replace(tzinfo=HKT).astimezone(timezone.utc)
    except ValueError:
        return None

def read_official(xml_bytes,html,now):
    root=ElementTree.fromstring(xml_bytes)
    p=MatchIndex()
    p.feed(html)
    results=[]
    seen=set()
    for m in root.findall("m"):
        number=m.get("matchnum")
        if not number or number in p.duplicates or number in seen:
            continue
        seen.add(number)
        idx=p.matches.get(number)
        if not idx or not m.get("id") or idx.get("data-id")!=m.get("id"):
            continue
        when=to_utc_china(f'{idx["data-matchdate"]} {idx["data-matchtime"]}')
        if not when or when<now-timedelta(hours=2) or when>now+timedelta(hours=48):
            continue
        quote=m.find("row")
        if quote is None or not quote.get("updatetime"):
            continue
        updated=to_utc_china(quote.get("updatetime"))
        if not updated or updated>now+timedelta(minutes=5):
            continue
        try:
            prices=[float(quote.get(k,"")) for k in ("win","draw","lost")]
        except ValueError:
            continue
        if not all(1.01<=x<=100 for x in prices):
            continue
        results.append({
            "source_event_id":m.get("id"),"source_matchnum":number,
            "source_home":m.get("home"),"source_away":m.get("away"),
            "source_league":m.get("league"),"kickoff":when.isoformat(),
            "source_updated_at":updated.isoformat(),"home":prices[0],
            "draw":prices[1],"away":prices[2],
        })
    return results

def resolve_canonical(source,fixtures,now):
    if not isinstance(fixtures,list) or len(fixtures)>350:
        raise ValueError("canonical fixture feed missing/oversized")
    catalog={}
    for f in fixtures:
        if not isinstance(f,dict) or not str(f.get("id","")).strip():
            continue
        when=iso_time(f.get("kickoff"))
        if not when or when<now-timedelta(hours=2) or when>now+timedelta(hours=48):
            continue
        home=norm(f.get("home"));away=norm(f.get("away"))
        if home and away and home!=away:
            catalog.setdefault((home,away),[]).append((f,when))
    matches=[]
    collision=set()
    for row in source:
        config=VERIFIED_LEAGUES.get(row["source_league"])
        if not config:
            continue
        home=config[1].get(row["source_home"])
        away=config[1].get(row["source_away"])
        if not home or not away or home==away:
            continue
        when=iso_time(row["kickoff"])
        if not when:
            continue
        good=[f for f,k in catalog.get((norm(home),norm(away)),[])
              if abs((when-k).total_seconds())<=600 and
                 verified_canonical_league(row["source_league"],f.get("league"))]
        if len(good)!=1:
            continue
        fid=str(good[0]["id"])
        if fid in {x["match_id"] for x in matches}:
            collision.add(fid)
            continue
        matches.append(dict(row,match_id=fid,canonical_home=good[0]["home"],
                            canonical_away=good[0]["away"],canonical_league=good[0]["league"],
                            identity_method="VERIFIED_TEAM_PAIR_AND_KICKOFF",
                            provider="CHINA_500_SPF",captured_at=now.isoformat()))
    return [row for row in matches if row["match_id"] not in collision]

def get(url,max_bytes):
    r=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (FastTracker/500-SPF-Reader)","Accept":"application/json,text/html,application/xml","Cache-Control":"no-cache"})
    with urllib.request.urlopen(r,timeout=15) as response:
        body=response.read(max_bytes+1)
    if len(body)>max_bytes:
        raise ValueError("provider payload exceeded size limit")
    return body

def capture():
    now=datetime.now(timezone.utc)
    raw_json=json.loads(get(FIXTURES_URL,2_000_000))
    if not isinstance(raw_json,dict) or not isinstance(raw_json.get("matches"),list):
        raise ValueError("canonical summary absent")
    if not str(raw_json.get("source","")).startswith(("flashscore-single-rpc-canonical","supabase-canonical-live","flashscore-direct")):
        raise ValueError("untrusted fixture-feed provenance")
    source=read_official(get(XML_URL,500_000),get(INDEX_URL,2_000_000).decode("utf-8","replace"),now)
    matched=resolve_canonical(source,raw_json["matches"],now)
    output={"source":"CHINA_500_SPF","captured_at":now.isoformat(),"source_rows":len(source),
            "canonical_targets":len(raw_json["matches"]),"accepted":len(matched),"rows":matched}
    OUTPUT.write_text(json.dumps(output,ensure_ascii=False),encoding="utf-8")
    print("CHINA_500_SPF_CAPTURE "+json.dumps({
        "source_rows":len(source),"canonical_targets":len(raw_json["matches"]),
        "verified":len(matched),"ids":[x["match_id"] for x in matched],
        "publication":False},sort_keys=True))
    return 0  # A match-free schedule is a valid no-op, never publish an empty batch.

if __name__=="__main__":
    try:
        raise SystemExit(capture())
    except (OSError,ValueError,ElementTree.ParseError,KeyError,TypeError) as e:
        print("CHINA_500_SPF_UNAVAILABLE",type(e).__name__,str(e)[:180],file=sys.stderr)
        raise SystemExit(2)
