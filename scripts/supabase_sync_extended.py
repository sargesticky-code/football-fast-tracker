#!/usr/bin/env python3
"""Sync secondary Fast Tracker feeds into Supabase.

Run after scripts/supabase_sync.py so referenced HKJC match rows exist.
"""

from __future__ import annotations
import csv, io, json, os
from pathlib import Path
from typing import Any
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
LIVE_CSV_URL = os.environ.get(
    "FAST_TRACKER_LIVE_CSV_URL",
    "https://football-fast-tracker-live-sargesticky-9289.vercel.app/api/live_scores?format=csv"
)

def blank(v): return v is None or str(v).strip() == ""
def text(v): return None if blank(v) else str(v).strip()
def num(v):
    if blank(v): return None
    try: return float(str(v).strip())
    except ValueError: return None
def integer(v):
    if blank(v): return None
    try: return int(float(str(v).strip()))
    except ValueError: return None
def boolean(v):
    if blank(v): return None
    return str(v).strip().lower() in {"1","true","yes","y"}

def read_csv(path: Path):
    if not path.exists(): return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def post(table, rows, conflict, batch=250):
    if not rows: return 0
    headers={"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"application/json",
             "Prefer":"resolution=merge-duplicates,return=minimal"}
    total=0
    for i in range(0,len(rows),batch):
        chunk=rows[i:i+batch]
        res=requests.post(f"{URL}/rest/v1/{table}",params={"on_conflict":conflict},
                          headers=headers,data=json.dumps(chunk,ensure_ascii=False),timeout=60)
        if not res.ok:
            raise RuntimeError(f"{table}: {res.status_code} {res.text[:800]}")
        total += len(chunk)
    return total

def map_rows(filename, mapper):
    return [x for r in read_csv(DATA/filename) if (x:=mapper(r)) is not None]

def sync_supplement():
    rows=map_rows("forebet_supplement_current.csv", lambda r: None if blank(r.get("hkjc_event_id")) else {
      "hkjc_event_id":text(r.get("hkjc_event_id")),"fetched_at":text(r.get("fetched_at_hkt")),
      "kickoff_hkt":text(r.get("kickoff_hkt")),"hkjc_league":text(r.get("hkjc_league")),
      "home_en":text(r.get("home_en")),"away_en":text(r.get("away_en")),
      "prob_home":num(r.get("prob_home")),"prob_draw":num(r.get("prob_draw")),"prob_away":num(r.get("prob_away")),
      "prediction_1x2":text(r.get("prediction_1x2")),"predicted_score":text(r.get("predicted_score")),
      "avg_goals":num(r.get("avg_goals")),"source_url":text(r.get("source_url")),"match_score":num(r.get("match_score")),
      "status":text(r.get("status")),"notes":text(r.get("notes")),"prediction_ou25":text(r.get("prediction_ou25")),
      "prob_over25":num(r.get("prob_over25")),"prob_under25":num(r.get("prob_under25")),
      "ou_predicted_score":text(r.get("ou_predicted_score")),"corner_prediction":text(r.get("corner_prediction")),
      "corner_prob_under95":num(r.get("corner_prob_under95")),"corner_prob_over95":num(r.get("corner_prob_over95")),
      "corner_predicted_score":text(r.get("corner_predicted_score")),"avg_corners":num(r.get("avg_corners")),"raw":r})
    return post("forebet_supplement",rows,"hkjc_event_id")

def sync_archive():
    rows=map_rows("forebet_archive.csv", lambda r: None if blank(r.get("hkjc_event_id")) or blank(r.get("captured_at_hkt")) else {
      "hkjc_event_id":text(r.get("hkjc_event_id")),"captured_at":text(r.get("captured_at_hkt")),
      "hkjc_league":text(r.get("hkjc_league")),"hkjc_home_team":text(r.get("hkjc_home_team")),
      "hkjc_away_team":text(r.get("hkjc_away_team")),"hkjc_home_zh":text(r.get("hkjc_home_zh")),
      "hkjc_away_zh":text(r.get("hkjc_away_zh")),"hkjc_kickoff_hkt":text(r.get("hkjc_kickoff_hkt")),
      "prob_home":num(r.get("prob_home")),"prob_draw":num(r.get("prob_draw")),"prob_away":num(r.get("prob_away")),
      "prediction_1x2":text(r.get("prediction_1x2")),"predicted_score":text(r.get("predicted_score")),
      "avg_goals":num(r.get("avg_goals")),"power_home":num(r.get("power_home")),"power_away":num(r.get("power_away")),
      "power_source":text(r.get("power_source")),"power_updated":text(r.get("power_updated")),
      "prediction_ou25":text(r.get("prediction_ou25")),"prob_over25":num(r.get("prob_over25")),
      "prob_under25":num(r.get("prob_under25")),"ou_predicted_score":text(r.get("ou_predicted_score")),
      "corner_prediction":text(r.get("corner_prediction")),"corner_prob_under95":num(r.get("corner_prob_under95")),
      "corner_prob_over95":num(r.get("corner_prob_over95")),"corner_predicted_score":text(r.get("corner_predicted_score")),
      "avg_corners":num(r.get("avg_corners")),"forebet_detail_url":text(r.get("forebet_detail_url")),"raw":r})
    return post("forebet_archive",rows,"hkjc_event_id,captured_at")

def sync_availability():
    rows=map_rows("forebet_availability.csv", lambda r: None if blank(r.get("hkjc_event_id")) else {
      "hkjc_event_id":text(r.get("hkjc_event_id")),"checked_at":text(r.get("checked_at_hkt")),
      "match_date":text(r.get("match_date")),"kickoff_hkt":text(r.get("kickoff_hkt")),
      "league_zh":text(r.get("league_zh")),"home_en":text(r.get("home_en")),"away_en":text(r.get("away_en")),
      "state":text(r.get("state")),"reason":text(r.get("reason")),"raw":r})
    return post("forebet_availability",rows,"hkjc_event_id")

def sync_bet365():
    rows=map_rows("bet365_current.csv", lambda r: None if blank(r.get("hkjc_event_id")) else {
      "hkjc_event_id":text(r.get("hkjc_event_id")),"fetched_at":text(r.get("fetched_at_hkt")),
      "match_date":text(r.get("match_date")),"kickoff_hkt":text(r.get("kickoff_hkt")),"league":text(r.get("league")),
      "home":text(r.get("home")),"away":text(r.get("away")),"bet365_home":num(r.get("bet365_home")),
      "bet365_draw":num(r.get("bet365_draw")),"bet365_away":num(r.get("bet365_away")),
      "bet365_fixture_id":text(r.get("bet365_fixture_id")),"match_quality":num(r.get("match_quality")),
      "source":text(r.get("source")),"raw":r})
    return post("bet365_current",rows,"hkjc_event_id")

def sync_form():
    rows=map_rows("form_current.csv", lambda r: None if blank(r.get("hkjc_event_id")) else {
      "hkjc_event_id":text(r.get("hkjc_event_id")),"fetched_at":text(r.get("fetched_at_hkt")),
      "home":text(r.get("home")),"away":text(r.get("away")),"form_prob_home":num(r.get("form_prob_home")),
      "form_prob_draw":num(r.get("form_prob_draw")),"form_prob_away":num(r.get("form_prob_away")),
      "form_xg_home":num(r.get("form_xg_home")),"form_xg_away":num(r.get("form_xg_away")),
      "home_games":integer(r.get("home_games")),"away_games":integer(r.get("away_games")),
      "home_venue_games":integer(r.get("home_venue_games")),"away_venue_games":integer(r.get("away_venue_games")),
      "quality":text(r.get("quality")),"model_source":text(r.get("model_source")),"raw":r})
    return post("form_predictions",rows,"hkjc_event_id")

def sync_evaluation():
    rows=map_rows("evaluation_summary.csv", lambda r: None if blank(r.get("model")) else {
      "model":text(r.get("model")),"as_of_hkt":text(r.get("as_of_hkt")),
      "settled_matches":integer(r.get("settled_matches")),"avg_rps":num(r.get("avg_rps")),
      "avg_brier":num(r.get("avg_brier")),"avg_logloss":num(r.get("avg_logloss")),"raw":r})
    return post("evaluation_summary",rows,"model")

def sync_movement():
    rows=map_rows("odds_movement.csv", lambda r: None if blank(r.get("hkjc_event_id")) else {
      "hkjc_event_id":text(r.get("hkjc_event_id")),"captured_at":text(r.get("captured_at_hkt")),
      "kickoff_hkt":text(r.get("kickoff_hkt")),"home":text(r.get("home")),"away":text(r.get("away")),
      "movement_side":text(r.get("movement_side")),"now_odds":num(r.get("now_odds")),"odds_24h":num(r.get("odds_24h")),
      "move_24h_pp":num(r.get("move_24h_pp")),"odds_2h":num(r.get("odds_2h")),"move_2h_pp":num(r.get("move_2h_pp")),
      "odds_1h":num(r.get("odds_1h")),"move_1h_pp":num(r.get("move_1h_pp")),"vol_24h_pp":num(r.get("vol_24h_pp")),
      "signal":text(r.get("signal")),"model_side":text(r.get("model_side")),"model_prob":num(r.get("model_prob")),
      "model_alignment":text(r.get("model_alignment")),"match_confidence":num(r.get("match_confidence")),
      "alert_score":num(r.get("alert_score")),"raw":r})
    return post("odds_movement_current",rows,"hkjc_event_id")

def sync_fallback():
    rows=map_rows("prediction_fallback_current.csv", lambda r: None if blank(r.get("hkjc_event_id")) else {
      "hkjc_event_id":text(r.get("hkjc_event_id")),"fetched_at":text(r.get("fetched_at_hkt")),
      "kickoff_hkt":text(r.get("kickoff_hkt")),"hkjc_league":text(r.get("hkjc_league")),
      "home_en":text(r.get("home_en")),"away_en":text(r.get("away_en")),"source":text(r.get("source")),
      "source_competition":text(r.get("source_competition")),"source_url":text(r.get("source_url")),
      "recommendation":text(r.get("recommendation")),"market":text(r.get("market")),
      "match_score":num(r.get("match_score")),"status":text(r.get("status")),"notes":text(r.get("notes")),"raw":r})
    return post("prediction_fallback_current",rows,"hkjc_event_id")

def sync_live_score():
    if not URL or not KEY: raise RuntimeError("Supabase env vars required")
    res=requests.get(LIVE_CSV_URL,timeout=30)
    res.raise_for_status()
    src=list(csv.DictReader(io.StringIO(res.text.lstrip("\ufeff"))))
    rows=[]
    for r in src:
      event=text(r.get("hkjc_event_id"))
      if not event: continue
      rows.append({
        "hkjc_event_id":event,"updated_at_source":text(r.get("updatedAt")),"kickoff_hkt":text(r.get("kickoff_hkt")),
        "league":text(r.get("league")),"home_en":text(r.get("home_en")),"away_en":text(r.get("away_en")),
        "live_score":text(r.get("live_score")),"home_score":integer(r.get("home_score")),"away_score":integer(r.get("away_score")),
        "minute":integer(r.get("minute")),"match_status":text(r.get("match_status")),"source":text(r.get("source")),
        "source_match_id":text(r.get("source_match_id")),"source_home":text(r.get("source_home")),"source_away":text(r.get("source_away")),
        "match_confidence":num(r.get("match_confidence")),"source_updated_at":text(r.get("source_updated_at")),
        "home_corners":integer(r.get("home_corners")),"away_corners":integer(r.get("away_corners")),
        "total_corners":integer(r.get("total_corners")),"corner_line_ref":text(r.get("corner_line_ref")),
        "corners_to_hi":num(r.get("corners_to_hi")),"corner_progress":text(r.get("corner_progress")),"raw":r})
    return post("live_score_current",rows,"hkjc_event_id")

def main():
    counts={
      "forebet_supplement":sync_supplement(),
      "forebet_archive":sync_archive(),
      "forebet_availability":sync_availability(),
      "bet365":sync_bet365(),
      "form":sync_form(),
      "evaluation":sync_evaluation(),
      "odds_movement":sync_movement(),
      "prediction_fallback":sync_fallback(),
      "live_score":sync_live_score(),
    }
    print(json.dumps({"ok":True,"rows":counts},ensure_ascii=False))

if __name__=="__main__":
    main()
