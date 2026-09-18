"""Capture current HKJC in-play HAD / HIL / CHL odds with bounded requests.

Designed for a 5-minute GitHub Actions refresh:
- 1 HAD page request every run
- only if HAD reports at least one in-play match, add 1 HIL + 1 CHL request
- no per-match fan-out
- output only currently in-play HKJC matches
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "hkjc_live_odds.csv"
HKT = ZoneInfo("Asia/Hong_Kong")

UPSTREAM = os.environ.get("HKJC_SCRAPER_PATH", "/tmp/hkjc-live")
sys.path.insert(0, UPSTREAM)

from hkjc.scraper import HKJCFootball, flatten_odds  # noqa: E402

COLUMNS = [
    "fetched_at_hkt", "hkjc_event_id", "match_id", "kickoff_hkt",
    "status", "tournament", "home_en", "away_en", "home_zh", "away_zh",
    "had_home", "had_draw", "had_away",
    "hil_line", "hil_over", "hil_under",
    "chl_line", "chl_over", "chl_under",
    "pool_status", "odds_updated_at",
]


def clean(v):
    return "" if v is None else str(v).strip()


def truthy(v):
    if isinstance(v, bool):
        return v
    return clean(v).lower() in {"1", "true", "yes", "y"}


def price(v):
    try:
        x = float(v)
        return x if x > 1 else ""
    except (TypeError, ValueError):
        return ""


def choose_two_way(rows, odds_type):
    grouped = {}
    for r in rows:
        if clean(r.get("odds_type")).upper() != odds_type:
            continue
        if not truthy(r.get("in_play")):
            continue
        if clean(r.get("comb_status")).upper() not in {"", "AVAILABLE"}:
            continue
        eid = clean(r.get("front_end_id"))
        if not eid:
            continue
        line = clean(r.get("condition"))
        key = (eid, line)
        rec = grouped.setdefault(key, {
            "event_id": eid,
            "line": line,
            "main": False,
            "over": "",
            "under": "",
            "updated_at": "",
        })
        rec["main"] = rec["main"] or truthy(r.get("main_line"))
        sel = clean(r.get("selection")).upper()
        if sel == "H":
            rec["over"] = price(r.get("odds"))
        elif sel == "L":
            rec["under"] = price(r.get("odds"))
        if clean(r.get("updated_at")):
            rec["updated_at"] = clean(r.get("updated_at"))

    by_event = {}
    for rec in grouped.values():
        if rec["over"] == "" or rec["under"] == "":
            continue
        by_event.setdefault(rec["event_id"], []).append(rec)

    chosen = {}
    for eid, candidates in by_event.items():
        main = next((x for x in candidates if x["main"]), None)
        chosen[eid] = main or candidates[0]
    return chosen


def write_rows(rows):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in COLUMNS})
    tmp.replace(OUT)


def main():
    fb = HKJCFootball()
    fetched = datetime.now(HKT).replace(microsecond=0).isoformat()

    # This page is known-good and already returns in-play rows when a match is live.
    had_rows = flatten_odds(fb.fetch_odds("HAD"))
    live_had = [
        r for r in had_rows
        if truthy(r.get("in_play"))
        and clean(r.get("comb_status")).upper() in {"", "AVAILABLE"}
    ]
    live_ids = sorted({clean(r.get("front_end_id")) for r in live_had if clean(r.get("front_end_id"))})

    # Preserve an explicit empty state after the last live match.
    if not live_ids:
        write_rows([])
        print("HKJC_LIVE_ODDS live=0 requests=1")
        return 0

    # Only two additional page-level calls. No per-match fan-out.
    hil_rows = flatten_odds(fb.fetch_odds("HIL"))
    chl_rows = flatten_odds(fb.fetch_odds("CHL"))
    hil = choose_two_way(hil_rows, "HIL")
    chl = choose_two_way(chl_rows, "CHL")

    base = {}
    for r in live_had:
        eid = clean(r.get("front_end_id"))
        if eid not in live_ids:
            continue
        rec = base.setdefault(eid, {
            "fetched_at_hkt": fetched,
            "hkjc_event_id": eid,
            "match_id": clean(r.get("match_id")),
            "kickoff_hkt": clean(r.get("kick_off")),
            "status": clean(r.get("status")),
            "tournament": clean(r.get("tournament")),
            "home_en": clean(r.get("home")),
            "away_en": clean(r.get("away")),
            "home_zh": clean(r.get("home_ch")),
            "away_zh": clean(r.get("away_ch")),
            "had_home": "", "had_draw": "", "had_away": "",
            "hil_line": "", "hil_over": "", "hil_under": "",
            "chl_line": "", "chl_over": "", "chl_under": "",
            "pool_status": clean(r.get("pool_status")),
            "odds_updated_at": clean(r.get("updated_at")),
        })
        sel = clean(r.get("selection")).upper()
        p = price(r.get("odds"))
        if sel == "H":
            rec["had_home"] = p
        elif sel == "D":
            rec["had_draw"] = p
        elif sel == "A":
            rec["had_away"] = p
        if clean(r.get("pool_status")):
            rec["pool_status"] = clean(r.get("pool_status"))
        if clean(r.get("updated_at")) > clean(rec.get("odds_updated_at")):
            rec["odds_updated_at"] = clean(r.get("updated_at"))

    out = []
    for eid in live_ids:
        rec = base.get(eid)
        if not rec:
            continue
        h = hil.get(eid) or {}
        c = chl.get(eid) or {}
        rec.update({
            "hil_line": h.get("line", ""),
            "hil_over": h.get("over", ""),
            "hil_under": h.get("under", ""),
            "chl_line": c.get("line", ""),
            "chl_over": c.get("over", ""),
            "chl_under": c.get("under", ""),
        })
        latest = max(
            clean(rec.get("odds_updated_at")),
            clean(h.get("updated_at")),
            clean(c.get("updated_at")),
        )
        rec["odds_updated_at"] = latest
        out.append(rec)

    out.sort(key=lambda r: (r["kickoff_hkt"], r["hkjc_event_id"]))
    write_rows(out)

    had_triplets = sum(
        bool(r["had_home"] and r["had_draw"] and r["had_away"]) for r in out
    )
    hil_pairs = sum(bool(r["hil_over"] and r["hil_under"]) for r in out)
    chl_pairs = sum(bool(r["chl_over"] and r["chl_under"]) for r in out)
    print(
        f"HKJC_LIVE_ODDS live={len(out)} requests=3 "
        f"HAD={had_triplets} HIL={hil_pairs} CHL={chl_pairs}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
