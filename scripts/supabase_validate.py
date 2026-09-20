#!/usr/bin/env python3
"""Post-migration parity checks for Fast Tracker Supabase."""
from __future__ import annotations
import csv, os, json
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
URL=os.environ["SUPABASE_URL"].rstrip("/")
KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HEAD={"apikey":KEY,"Authorization":f"Bearer {KEY}"}

def rows(path):
    p=DATA/path
    if not p.exists(): return []
    with p.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def count(table, filters=""):
    url=f"{URL}/rest/v1/{table}?select=*"
    if filters: url += "&"+filters
    r=requests.get(url,headers={**HEAD,"Prefer":"count=exact","Range":"0-0"},timeout=30)
    r.raise_for_status()
    cr=r.headers.get("Content-Range","*/0")
    return int(cr.split("/")[-1])

def sample(table, ids):
    if not ids: return []
    val="(" + ",".join(ids) + ")"
    r=requests.get(
        f"{URL}/rest/v1/{table}",
        params={"select":"*","hkjc_event_id":f"in.{val}"},
        headers=HEAD,timeout=30
    )
    r.raise_for_status()
    return r.json()

def main():
    h=[r for r in rows("hkjc_current.csv") if r.get("hkjc_event_id")]
    fb=[r for r in rows("forebet_current.csv") if r.get("hkjc_event_id")]
    md=[r for r in rows("model_current.csv") if r.get("hkjc_event_id")]
    al=[r for r in rows("team_alias_registry.csv") if r.get("forebet_alias")]
    selling=[r for r in h if str(r.get("selling","")).strip().lower() in {"1","true","yes","y"}
             and r.get("had_home") and r.get("had_draw") and r.get("had_away")]

    actual={
      "matches_current_or_history":count("matches"),
      "selling_had":count("fast_tracker_live_v2"),
      "forebet_current":count("forebet_predictions"),
      "models":count("model_predictions"),
      "aliases":count("team_aliases"),
    }
    expected={
      "hkjc_current":len(h),
      "selling_had":len(selling),
      "forebet_current":len(fb),
      "models":len(md),
      "aliases":len(al),
    }
    checks={
      "selling_had":actual["selling_had"]==expected["selling_had"],
      "forebet_current":actual["forebet_current"]==expected["forebet_current"],
      "models":actual["models"]==expected["models"],
      "aliases":actual["aliases"]==expected["aliases"],
    }
    ids=[r["hkjc_event_id"] for r in selling[:5]]
    result={"ok":all(checks.values()),"expected":expected,"actual":actual,"checks":checks,
            "sample_fast_tracker_live_v2":sample("fast_tracker_live_v2",ids)}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["ok"]:
        raise SystemExit(2)

if __name__=="__main__":
    main()
