#!/usr/bin/env python3
"""One-shot readable coverage inventory, never publishing 500 source rows."""
import sys, json
from collections import Counter
from datetime import datetime,timezone
sys.path.insert(0,"scripts")
from capture_500_spf import get, read_official, XML_URL, INDEX_URL, FIXTURES_URL, iso_time
now=datetime.now(timezone.utc)
rows=read_official(get(XML_URL,500_000),get(INDEX_URL,2_000_000).decode("utf-8","replace"),now)
feed=json.loads(get(FIXTURES_URL,2_000_000))
fixtures=feed.get("matches",[])
print("FT500_SOURCE_LEAGUE_COUNTS",json.dumps(dict(Counter(x["source_league"] for x in rows)),ensure_ascii=False))
for row in rows:
    when=iso_time(row["kickoff"])
    candidate=[f for f in fixtures if isinstance(f,dict) and iso_time(f.get("kickoff")) and
       abs((iso_time(f["kickoff"])-when).total_seconds())<=600]
    candidate=candidate[:16]
    print("FT500_CANDIDATE",json.dumps({
       "source_match_id":row["source_event_id"],"league_cn":row["source_league"],
       "home_cn":row["source_home"],"away_cn":row["source_away"],
       "utc":row["kickoff"],"source_updated_at":row["source_updated_at"],
       "candidates_at_kickoff":len(candidate),
       "canonical":[{"id":f.get("id"),"league":f.get("league"),"home":f.get("home"),"away":f.get("away")} for f in candidate]
    },ensure_ascii=False))
print("FT500_COVERAGE_SUMMARY",json.dumps({"source_valid":len(rows),"canonical_targets":len(fixtures)},sort_keys=True))
