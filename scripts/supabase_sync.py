#!/usr/bin/env python3
"""Sync Fast Tracker GitHub CSV feeds into Supabase.

Required environment variables:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

This intentionally uses Supabase's PostgREST endpoint via requests so the
production pipeline stays small and portable.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def blank(v: Any) -> bool:
    return v is None or str(v).strip() == ""


def num(v: Any):
    if blank(v):
        return None
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def integer(v: Any):
    if blank(v):
        return None
    try:
        return int(float(str(v).strip()))
    except ValueError:
        return None


def boolean(v: Any):
    if blank(v):
        return None
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def text(v: Any):
    return None if blank(v) else str(v).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def api_headers(prefer: str | None = None) -> dict[str, str]:
    if not URL or not KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    h = {
        "apikey": KEY,
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def upsert(table: str, rows: list[dict[str, Any]], conflict: str, batch: int = 300) -> int:
    total = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        r = requests.post(
            f"{URL}/rest/v1/{table}",
            params={"on_conflict": conflict},
            headers=api_headers("resolution=merge-duplicates,return=minimal"),
            data=json.dumps(chunk, ensure_ascii=False),
            timeout=60,
        )
        if not r.ok:
            raise RuntimeError(f"{table} upsert failed {r.status_code}: {r.text[:1000]}")
        total += len(chunk)
    return total


def sync_hkjc() -> int:
    src = read_csv(DATA / "hkjc_current.csv")
    matches: list[dict[str, Any]] = []
    odds: list[dict[str, Any]] = []
    for r in src:
        event = text(r.get("hkjc_event_id"))
        if not event:
            continue
        matches.append({
            "hkjc_event_id": event,
            "hkjc_match_id": text(r.get("match_id")),
            "kickoff_hkt": text(r.get("kickoff_hkt")),
            "status": text(r.get("status")),
            "tournament": text(r.get("tournament")),
            "home_en": text(r.get("home_en")),
            "away_en": text(r.get("away_en")),
            "home_zh": text(r.get("home_zh")),
            "away_zh": text(r.get("away_zh")),
            "pools": text(r.get("pools")),
            "pool_status": text(r.get("pool_status")),
            "in_play": boolean(r.get("in_play")),
            "selling": boolean(r.get("selling")),
            "fetched_at": text(r.get("fetched_at_hkt")),
            "source_updated_at": text(r.get("odds_updated_at")),
            "raw": r,
        })
        odds.append({
            "hkjc_event_id": event,
            "had_home": num(r.get("had_home")),
            "had_draw": num(r.get("had_draw")),
            "had_away": num(r.get("had_away")),
            "hil_line": text(r.get("hil_line")),
            "hil_over": num(r.get("hil_over")),
            "hil_under": num(r.get("hil_under")),
            "chl_line": text(r.get("chl_line")),
            "chl_over": num(r.get("chl_over")),
            "chl_under": num(r.get("chl_under")),
            "fetched_at": text(r.get("fetched_at_hkt")),
            "odds_updated_at": text(r.get("odds_updated_at")),
            "raw": r,
        })
    upsert("matches", matches, "hkjc_event_id")
    upsert("hkjc_odds_current", odds, "hkjc_event_id")
    return len(matches)


def sync_forebet() -> int:
    src = read_csv(DATA / "forebet_current.csv")
    rows = []
    for r in src:
        event = text(r.get("hkjc_event_id"))
        if not event:
            continue
        rows.append({
            "hkjc_event_id": event,
            "fetched_at": text(r.get("fetched_at_hkt")),
            "forebet_match_date": text(r.get("match_date")),
            "forebet_kickoff_text": text(r.get("kickoff_text")),
            "forebet_league_short": text(r.get("league_short")),
            "forebet_home_team": text(r.get("home_team")),
            "forebet_away_team": text(r.get("away_team")),
            "prob_home": num(r.get("prob_home")),
            "prob_draw": num(r.get("prob_draw")),
            "prob_away": num(r.get("prob_away")),
            "prediction_1x2": text(r.get("prediction_1x2")),
            "predicted_score": text(r.get("predicted_score")),
            "avg_goals": num(r.get("avg_goals")),
            "odds_home": num(r.get("odds_home")),
            "odds_draw": num(r.get("odds_draw")),
            "odds_away": num(r.get("odds_away")),
            "prediction_ou25": text(r.get("prediction_ou25")),
            "prob_over25": num(r.get("prob_over25")),
            "prob_under25": num(r.get("prob_under25")),
            "odds_over25": num(r.get("odds_over25")),
            "odds_under25": num(r.get("odds_under25")),
            "forebet_detail_url": text(r.get("forebet_detail_url")),
            "match_score": num(r.get("match_score")),
            "ou_predicted_score": text(r.get("ou_predicted_score")),
            "corner_prediction": text(r.get("corner_prediction")),
            "corner_prob_under95": num(r.get("corner_prob_under95")),
            "corner_prob_over95": num(r.get("corner_prob_over95")),
            "corner_predicted_score": text(r.get("corner_predicted_score")),
            "avg_corners": num(r.get("avg_corners")),
            "power_home": num(r.get("power_home")),
            "power_away": num(r.get("power_away")),
            "power_home_name": text(r.get("power_home_name")),
            "power_away_name": text(r.get("power_away_name")),
            "power_source": text(r.get("power_source")),
            "power_updated": text(r.get("power_updated")),
            "power_home_match": boolean(r.get("power_home_match")),
            "power_away_match": boolean(r.get("power_away_match")),
            "raw": r,
        })
    return upsert("forebet_predictions", rows, "hkjc_event_id")


def sync_model() -> int:
    src = read_csv(DATA / "model_current.csv")
    rows = []
    for r in src:
        event = text(r.get("hkjc_event_id"))
        if not event:
            continue
        rows.append({
            "hkjc_event_id": event,
            "fetched_at": text(r.get("fetched_at_hkt")),
            "home": text(r.get("home")),
            "away": text(r.get("away")),
            "model_league": text(r.get("model_league")),
            "model_home_name": text(r.get("model_home_name")),
            "model_away_name": text(r.get("model_away_name")),
            "dc_prob_home": num(r.get("dc_prob_home")),
            "dc_prob_draw": num(r.get("dc_prob_draw")),
            "dc_prob_away": num(r.get("dc_prob_away")),
            "dc_xg_home": num(r.get("dc_xg_home")),
            "dc_xg_away": num(r.get("dc_xg_away")),
            "dc_prob_over25": num(r.get("dc_prob_over25")),
            "pi_prob_home": num(r.get("pi_prob_home")),
            "pi_prob_draw": num(r.get("pi_prob_draw")),
            "pi_prob_away": num(r.get("pi_prob_away")),
            "pi_home_rating": num(r.get("pi_home_rating")),
            "pi_away_rating": num(r.get("pi_away_rating")),
            "pi_diff": num(r.get("pi_diff")),
            "training_matches": integer(r.get("training_matches")),
            "team_match_quality": num(r.get("team_match_quality")),
            "quality": text(r.get("quality")),
            "model_source": text(r.get("model_source")),
            "raw": r,
        })
    return upsert("model_predictions", rows, "hkjc_event_id")


def sync_aliases() -> int:
    src = read_csv(DATA / "team_alias_registry.csv")
    rows = []
    for r in src:
        alias = text(r.get("forebet_alias"))
        canonical = text(r.get("canonical_hkjc_name"))
        if not alias or not canonical:
            continue
        rows.append({
            "source": "FOREBET",
            "alias": alias,
            "canonical_hkjc_name": canonical,
            "confidence": num(r.get("confidence")),
            "first_seen_hkt": text(r.get("first_seen_hkt")),
            "last_seen_hkt": text(r.get("last_seen_hkt")),
            "match_count": integer(r.get("match_count")),
            "status": text(r.get("status")),
            "alias_source": text(r.get("source")),
        })
    return upsert("team_aliases", rows, "source,alias")


def main() -> int:
    counts = {
        "hkjc": sync_hkjc(),
        "forebet": sync_forebet(),
        "model": sync_model(),
        "aliases": sync_aliases(),
    }
    print(json.dumps({"ok": True, "rows": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
