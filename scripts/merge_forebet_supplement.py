#!/usr/bin/env python3
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MAIN = DATA / "forebet_current.csv"
SUPP = DATA / "forebet_supplement_current.csv"
HKJC = DATA / "hkjc_current.csv"


def clean(v):
    return "" if v is None else str(v).strip()


def read_rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    if not MAIN.exists() or not SUPP.exists():
        raise SystemExit("main/supplement CSV missing")

    main_rows = read_rows(MAIN)
    supp_rows = read_rows(SUPP)
    hkjc_rows = read_rows(HKJC) if HKJC.exists() else []
    hkjc_by_id = {clean(r.get("hkjc_event_id")): r for r in hkjc_rows}
    existing = {clean(r.get("hkjc_event_id")) for r in main_rows}

    with MAIN.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        headers = next(reader)

    added = 0
    for s in supp_rows:
        eid = clean(s.get("hkjc_event_id"))
        if not eid or eid in existing:
            continue
        if clean(s.get("status")) not in ("OK", "REGRESSION_SEED"):
            continue
        if not all(clean(s.get(k)) for k in ("prob_home","prob_draw","prob_away","prediction_1x2")):
            continue

        h = hkjc_by_id.get(eid, {})
        kick = clean(s.get("kickoff_hkt"))
        match_date = kick[:10] if len(kick) >= 10 else ""
        row = {k: "" for k in headers}
        row.update({
            "fetched_at_hkt": clean(s.get("fetched_at_hkt")),
            "match_date": match_date,
            "kickoff_text": kick,
            "league_short": clean(s.get("hkjc_league")),
            "home_team": clean(s.get("home_en")),
            "away_team": clean(s.get("away_en")),
            "prob_home": clean(s.get("prob_home")),
            "prob_draw": clean(s.get("prob_draw")),
            "prob_away": clean(s.get("prob_away")),
            "prediction_1x2": clean(s.get("prediction_1x2")),
            "predicted_score": clean(s.get("predicted_score")),
            "avg_goals": clean(s.get("avg_goals")),
            "hkjc_event_id": eid,
            "hkjc_league": clean(h.get("tournament") or s.get("hkjc_league")),
            "hkjc_home_team": clean(h.get("home_en") or s.get("home_en")),
            "hkjc_away_team": clean(h.get("away_en") or s.get("away_en")),
            "hkjc_home_zh": clean(h.get("home_zh")),
            "hkjc_away_zh": clean(h.get("away_zh")),
            "hkjc_kickoff_hkt": clean(h.get("kickoff_hkt") or kick),
            "hkjc_had_home": clean(h.get("had_home")),
            "hkjc_had_draw": clean(h.get("had_draw")),
            "hkjc_had_away": clean(h.get("had_away")),
            "match_score": clean(s.get("match_score")),
            "forebet_detail_url": clean(s.get("source_url")),
        })
        main_rows.append(row)
        existing.add(eid)
        added += 1

    with MAIN.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        w.writerows(main_rows)

    print(f"merged {added} missing Forebet rows into {MAIN}")


if __name__ == "__main__":
    main()
