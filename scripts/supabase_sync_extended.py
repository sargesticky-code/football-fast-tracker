#!/usr/bin/env python3
"""Sync Fast Tracker secondary feeds into Supabase.

Run after supabase_sync.py. Historical rows create missing match-ledger stubs
without overwriting richer current HKJC records.
"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
LIVE_CSV_URL = os.environ.get(
    "FAST_TRACKER_LIVE_CSV_URL",
    "https://football-fast-tracker-live-sargesticky-9289.vercel.app/api/live_scores?format=csv",
)
HKT = timezone(timedelta(hours=8))


def blank(v):
    return v is None or str(v).strip() == ""


def text(v):
    return None if blank(v) else str(v).strip()


def num(v):
    if blank(v):
        return None
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def integer(v):
    if blank(v):
        return None
    try:
        return int(float(str(v).strip()))
    except ValueError:
        return None


def ts(v):
    """Normalize HKT/ISO text and Google/Excel serial datetimes."""
    if blank(v):
        return None
    s = str(v).strip()
    try:
        serial = float(s)
        if 20000 <= serial <= 80000:
            return (datetime(1899, 12, 30, tzinfo=HKT) + timedelta(days=serial)).isoformat()
    except ValueError:
        pass
    if s.endswith("Z") or "+" in s[10:] or ("-" in s[10:] and "T" in s):
        return s
    if len(s) == 10:
        return s + "T00:00:00+08:00"
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    return s + "+08:00"


def read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def api_headers(*, merge=True):
    if not URL or not KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    resolution = "merge-duplicates" if merge else "ignore-duplicates"
    return {
        "apikey": KEY,
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
        "Prefer": f"resolution={resolution},return=minimal",
    }


def upsert(table, rows, conflict, *, merge=True, batch=250):
    if not rows:
        return 0
    total = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        r = requests.post(
            f"{URL}/rest/v1/{table}",
            params={"on_conflict": conflict},
            headers=api_headers(merge=merge),
            data=json.dumps(chunk, ensure_ascii=False),
            timeout=60,
        )
        if not r.ok:
            raise RuntimeError(f"{table} upsert failed {r.status_code}: {r.text[:1000]}")
        total += len(chunk)
    return total


def ensure_match_stubs():
    stubs = {}

    def add(event, kickoff=None, league=None, home=None, away=None, home_zh=None, away_zh=None):
        event = text(event)
        if not event or event in stubs:
            return
        stubs[event] = {
            "hkjc_event_id": event,
            "kickoff_hkt": ts(kickoff),
            "tournament": text(league),
            "home_en": text(home),
            "away_en": text(away),
            "home_zh": text(home_zh),
            "away_zh": text(away_zh),
            "status": "HISTORICAL_STUB",
            "selling": False,
            "in_play": False,
            "raw": {"migration_stub": True},
        }

    for r in read_csv(DATA / "forebet_archive.csv"):
        add(
            r.get("hkjc_event_id"),
            r.get("hkjc_kickoff_hkt"),
            r.get("hkjc_league"),
            r.get("hkjc_home_team"),
            r.get("hkjc_away_team"),
            r.get("hkjc_home_zh"),
            r.get("hkjc_away_zh"),
        )

    specs = [
        ("forebet_supplement_current.csv", "kickoff_hkt", "hkjc_league", "home_en", "away_en"),
        ("forebet_availability.csv", "kickoff_hkt", "league_zh", "home_en", "away_en"),
        ("bet365_current.csv", "kickoff_hkt", "league", "home", "away"),
        ("form_current.csv", None, None, "home", "away"),
        ("odds_movement.csv", "kickoff_hkt", None, "home", "away"),
        ("prediction_fallback_current.csv", "kickoff_hkt", "hkjc_league", "home_en", "away_en"),
    ]
    for filename, kickoff_key, league_key, home_key, away_key in specs:
        for r in read_csv(DATA / filename):
            add(
                r.get("hkjc_event_id"),
                r.get(kickoff_key) if kickoff_key else None,
                r.get(league_key) if league_key else None,
                r.get(home_key),
                r.get(away_key),
            )

    return upsert("matches", list(stubs.values()), "hkjc_event_id", merge=False)


def sync_supplement():
    rows = []
    for r in read_csv(DATA / "forebet_supplement_current.csv"):
        if blank(r.get("hkjc_event_id")):
            continue
        rows.append({
            "hkjc_event_id": text(r.get("hkjc_event_id")),
            "fetched_at": ts(r.get("fetched_at_hkt")),
            "kickoff_hkt": ts(r.get("kickoff_hkt")),
            "hkjc_league": text(r.get("hkjc_league")),
            "home_en": text(r.get("home_en")),
            "away_en": text(r.get("away_en")),
            "prob_home": num(r.get("prob_home")),
            "prob_draw": num(r.get("prob_draw")),
            "prob_away": num(r.get("prob_away")),
            "prediction_1x2": text(r.get("prediction_1x2")),
            "predicted_score": text(r.get("predicted_score")),
            "avg_goals": num(r.get("avg_goals")),
            "source_url": text(r.get("source_url")),
            "match_score": num(r.get("match_score")),
            "status": text(r.get("status")),
            "notes": text(r.get("notes")),
            "prediction_ou25": text(r.get("prediction_ou25")),
            "prob_over25": num(r.get("prob_over25")),
            "prob_under25": num(r.get("prob_under25")),
            "ou_predicted_score": text(r.get("ou_predicted_score")),
            "corner_prediction": text(r.get("corner_prediction")),
            "corner_prob_under95": num(r.get("corner_prob_under95")),
            "corner_prob_over95": num(r.get("corner_prob_over95")),
            "corner_predicted_score": text(r.get("corner_predicted_score")),
            "avg_corners": num(r.get("avg_corners")),
            "raw": r,
        })
    return upsert("forebet_supplement", rows, "hkjc_event_id")


def sync_archive():
    rows = []
    for r in read_csv(DATA / "forebet_archive.csv"):
        if blank(r.get("hkjc_event_id")) or blank(r.get("captured_at_hkt")):
            continue
        rows.append({
            "hkjc_event_id": text(r.get("hkjc_event_id")),
            "captured_at": ts(r.get("captured_at_hkt")),
            "hkjc_league": text(r.get("hkjc_league")),
            "hkjc_home_team": text(r.get("hkjc_home_team")),
            "hkjc_away_team": text(r.get("hkjc_away_team")),
            "hkjc_home_zh": text(r.get("hkjc_home_zh")),
            "hkjc_away_zh": text(r.get("hkjc_away_zh")),
            "hkjc_kickoff_hkt": ts(r.get("hkjc_kickoff_hkt")),
            "prob_home": num(r.get("prob_home")),
            "prob_draw": num(r.get("prob_draw")),
            "prob_away": num(r.get("prob_away")),
            "prediction_1x2": text(r.get("prediction_1x2")),
            "predicted_score": text(r.get("predicted_score")),
            "avg_goals": num(r.get("avg_goals")),
            "power_home": num(r.get("power_home")),
            "power_away": num(r.get("power_away")),
            "power_source": text(r.get("power_source")),
            "power_updated": ts(r.get("power_updated")),
            "prediction_ou25": text(r.get("prediction_ou25")),
            "prob_over25": num(r.get("prob_over25")),
            "prob_under25": num(r.get("prob_under25")),
            "ou_predicted_score": text(r.get("ou_predicted_score")),
            "corner_prediction": text(r.get("corner_prediction")),
            "corner_prob_under95": num(r.get("corner_prob_under95")),
            "corner_prob_over95": num(r.get("corner_prob_over95")),
            "corner_predicted_score": text(r.get("corner_predicted_score")),
            "avg_corners": num(r.get("avg_corners")),
            "forebet_detail_url": text(r.get("forebet_detail_url")),
            "raw": r,
        })
    return upsert("forebet_archive", rows, "hkjc_event_id,captured_at")


def sync_availability():
    rows = []
    for r in read_csv(DATA / "forebet_availability.csv"):
        if blank(r.get("hkjc_event_id")):
            continue
        rows.append({
            "hkjc_event_id": text(r.get("hkjc_event_id")),
            "checked_at": ts(r.get("checked_at_hkt")),
            "match_date": text(r.get("match_date")),
            "kickoff_hkt": ts(r.get("kickoff_hkt")),
            "league_zh": text(r.get("league_zh")),
            "home_en": text(r.get("home_en")),
            "away_en": text(r.get("away_en")),
            "state": text(r.get("state")),
            "reason": text(r.get("reason")),
            "raw": r,
        })
    return upsert("forebet_availability", rows, "hkjc_event_id")


def sync_bet365():
    rows = []
    for r in read_csv(DATA / "bet365_current.csv"):
        if blank(r.get("hkjc_event_id")):
            continue
        rows.append({
            "hkjc_event_id": text(r.get("hkjc_event_id")),
            "fetched_at": ts(r.get("fetched_at_hkt")),
            "match_date": text(r.get("match_date")),
            "kickoff_hkt": ts(r.get("kickoff_hkt")),
            "league": text(r.get("league")),
            "home": text(r.get("home")),
            "away": text(r.get("away")),
            "bet365_home": num(r.get("bet365_home")),
            "bet365_draw": num(r.get("bet365_draw")),
            "bet365_away": num(r.get("bet365_away")),
            "bet365_fixture_id": text(r.get("bet365_fixture_id")),
            "match_quality": num(r.get("match_quality")),
            "source": text(r.get("source")),
            "raw": r,
        })
    return upsert("bet365_current", rows, "hkjc_event_id")


def sync_form():
    rows = []
    for r in read_csv(DATA / "form_current.csv"):
        if blank(r.get("hkjc_event_id")):
            continue
        rows.append({
            "hkjc_event_id": text(r.get("hkjc_event_id")),
            "fetched_at": ts(r.get("fetched_at_hkt")),
            "home": text(r.get("home")),
            "away": text(r.get("away")),
            "form_prob_home": num(r.get("form_prob_home")),
            "form_prob_draw": num(r.get("form_prob_draw")),
            "form_prob_away": num(r.get("form_prob_away")),
            "form_xg_home": num(r.get("form_xg_home")),
            "form_xg_away": num(r.get("form_xg_away")),
            "home_games": integer(r.get("home_games")),
            "away_games": integer(r.get("away_games")),
            "home_venue_games": integer(r.get("home_venue_games")),
            "away_venue_games": integer(r.get("away_venue_games")),
            "quality": text(r.get("quality")),
            "model_source": text(r.get("model_source")),
            "raw": r,
        })
    return upsert("form_predictions", rows, "hkjc_event_id")


def sync_evaluation():
    rows = []
    for r in read_csv(DATA / "evaluation_summary.csv"):
        if blank(r.get("model")):
            continue
        rows.append({
            "model": text(r.get("model")),
            "as_of_hkt": ts(r.get("as_of_hkt")),
            "settled_matches": integer(r.get("settled_matches")),
            "avg_rps": num(r.get("avg_rps")),
            "avg_brier": num(r.get("avg_brier")),
            "avg_logloss": num(r.get("avg_logloss")),
            "raw": r,
        })
    return upsert("evaluation_summary", rows, "model")


def sync_movement():
    rows = []
    for r in read_csv(DATA / "odds_movement.csv"):
        if blank(r.get("hkjc_event_id")):
            continue
        rows.append({
            "hkjc_event_id": text(r.get("hkjc_event_id")),
            "captured_at": ts(r.get("captured_at_hkt")),
            "kickoff_hkt": ts(r.get("kickoff_hkt")),
            "home": text(r.get("home")),
            "away": text(r.get("away")),
            "movement_side": text(r.get("movement_side")),
            "now_odds": num(r.get("now_odds")),
            "odds_24h": num(r.get("odds_24h")),
            "move_24h_pp": num(r.get("move_24h_pp")),
            "odds_2h": num(r.get("odds_2h")),
            "move_2h_pp": num(r.get("move_2h_pp")),
            "odds_1h": num(r.get("odds_1h")),
            "move_1h_pp": num(r.get("move_1h_pp")),
            "vol_24h_pp": num(r.get("vol_24h_pp")),
            "signal": text(r.get("signal")),
            "model_side": text(r.get("model_side")),
            "model_prob": num(r.get("model_prob")),
            "model_alignment": text(r.get("model_alignment")),
            "match_confidence": num(r.get("match_confidence")),
            "alert_score": num(r.get("alert_score")),
            "raw": r,
        })
    return upsert("odds_movement_current", rows, "hkjc_event_id")


def sync_fallback():
    rows = []
    for r in read_csv(DATA / "prediction_fallback_current.csv"):
        if blank(r.get("hkjc_event_id")):
            continue
        rows.append({
            "hkjc_event_id": text(r.get("hkjc_event_id")),
            "fetched_at": ts(r.get("fetched_at_hkt")),
            "kickoff_hkt": ts(r.get("kickoff_hkt")),
            "hkjc_league": text(r.get("hkjc_league")),
            "home_en": text(r.get("home_en")),
            "away_en": text(r.get("away_en")),
            "source": text(r.get("source")),
            "source_competition": text(r.get("source_competition")),
            "source_url": text(r.get("source_url")),
            "recommendation": text(r.get("recommendation")),
            "market": text(r.get("market")),
            "match_score": num(r.get("match_score")),
            "status": text(r.get("status")),
            "notes": text(r.get("notes")),
            "raw": r,
        })
    return upsert("prediction_fallback_current", rows, "hkjc_event_id")


def sync_live_score():
    r = requests.get(LIVE_CSV_URL, timeout=30)
    r.raise_for_status()
    rows = []
    for src in csv.DictReader(io.StringIO(r.text.lstrip("\ufeff"))):
        event = text(src.get("hkjc_event_id"))
        if not event:
            continue
        rows.append({
            "hkjc_event_id": event,
            "updated_at_source": ts(src.get("updatedAt")),
            "kickoff_hkt": ts(src.get("kickoff_hkt")),
            "league": text(src.get("league")),
            "home_en": text(src.get("home_en")),
            "away_en": text(src.get("away_en")),
            "live_score": text(src.get("live_score")),
            "home_score": integer(src.get("home_score")),
            "away_score": integer(src.get("away_score")),
            "minute": integer(src.get("minute")),
            "match_status": text(src.get("match_status")),
            "source": text(src.get("source")),
            "source_match_id": text(src.get("source_match_id")),
            "source_home": text(src.get("source_home")),
            "source_away": text(src.get("source_away")),
            "match_confidence": num(src.get("match_confidence")),
            "source_updated_at": ts(src.get("source_updated_at")),
            "home_corners": integer(src.get("home_corners")),
            "away_corners": integer(src.get("away_corners")),
            "total_corners": integer(src.get("total_corners")),
            "corner_line_ref": text(src.get("corner_line_ref")),
            "corners_to_hi": num(src.get("corners_to_hi")),
            "corner_progress": text(src.get("corner_progress")),
            "raw": src,
        })
    return upsert("live_score_current", rows, "hkjc_event_id")


def main():
    counts = {
        "match_stubs": ensure_match_stubs(),
        "forebet_supplement": sync_supplement(),
        "forebet_archive": sync_archive(),
        "forebet_availability": sync_availability(),
        "bet365": sync_bet365(),
        "form": sync_form(),
        "evaluation": sync_evaluation(),
        "odds_movement": sync_movement(),
        "prediction_fallback": sync_fallback(),
        "live_score": sync_live_score(),
    }
    print(json.dumps({"ok": True, "rows": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
