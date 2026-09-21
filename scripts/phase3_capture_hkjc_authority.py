#!/usr/bin/env python3
"""Phase 3 Layer 1: one-request HKJC live-authority capture.

Authority capture is intentionally lighter than the legacy live-odds job:
one HAD page request only. It records HKJC match identity, match status and
pool selling status, plus a source timestamp even when zero live rows exist.

No Phase 1/2 data or production Google Sheet is read or written.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "phase3_hkjc_authority.json"
HKT = ZoneInfo("Asia/Hong_Kong")

UPSTREAM = os.environ.get("HKJC_SCRAPER_PATH", "/tmp/hkjc-phase3")
sys.path.insert(0, UPSTREAM)

from hkjc.scraper import HKJCFootball, flatten_odds  # noqa: E402


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def first(row: dict, *keys: str) -> str:
    for key in keys:
        value = clean(row.get(key))
        if value:
            return value
    return ""


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"1", "true", "yes", "y"}


def live_status(value) -> bool:
    s = clean(value).upper().replace("_", "").replace(" ", "")
    if not s:
        return False
    if any(x in s for x in (
        "PREEVENT", "ENDED", "FINISHED", "FULLTIME",
        "CANCEL", "POSTPON", "ABANDON",
    )):
        return False
    return any(x in s for x in (
        "FIRSTHALF", "SECONDHALF", "INPLAY",
        "EXTRATIME", "PENALTY",
    ))


def main() -> int:
    fetched_at = datetime.now(HKT).replace(microsecond=0).isoformat()
    fb = HKJCFootball()

    # Layer 1 authority needs only one lightweight HKJC market page.
    flat = flatten_odds(fb.fetch_odds("HAD"))

    by_event: dict[str, dict] = {}
    for row in flat:
        event_id = clean(row.get("front_end_id"))
        status = clean(row.get("status"))
        if not event_id or not live_status(status):
            continue

        # Preserve source-language fields when the upstream scraper exposes
        # them. Generic home/away remain the fallback so Layer 1 stays stable.
        home_en = first(row, "home_en", "home_name_en", "homeEnglish", "home")
        away_en = first(row, "away_en", "away_name_en", "awayEnglish", "away")
        home_zh = first(row, "home_zh", "home_name_zh", "homeChinese", "home_chi")
        away_zh = first(row, "away_zh", "away_name_zh", "awayChinese", "away_chi")

        rec = by_event.setdefault(event_id, {
            "hkjc_event_id": event_id,
            "match_id": clean(row.get("match_id")),
            "status": status,
            "pool_status": clean(row.get("pool_status")),
            "kickoff_hkt": clean(row.get("kick_off")),
            "tournament": clean(row.get("tournament")),
            "home_en": home_en,
            "away_en": away_en,
            "home_zh": home_zh,
            "away_zh": away_zh,
            "in_play": truthy(row.get("in_play")),
            "odds_updated_at": clean(row.get("updated_at")),
        })

        # Preserve the newest/non-empty HKJC state from this single response.
        if clean(row.get("match_id")):
            rec["match_id"] = clean(row.get("match_id"))
        if status:
            rec["status"] = status
        if clean(row.get("pool_status")):
            rec["pool_status"] = clean(row.get("pool_status"))
        if home_en:
            rec["home_en"] = home_en
        if away_en:
            rec["away_en"] = away_en
        if home_zh:
            rec["home_zh"] = home_zh
        if away_zh:
            rec["away_zh"] = away_zh
        rec["in_play"] = rec["in_play"] or truthy(row.get("in_play"))
        if clean(row.get("updated_at")) > clean(rec.get("odds_updated_at")):
            rec["odds_updated_at"] = clean(row.get("updated_at"))

    rows = sorted(
        by_event.values(),
        key=lambda r: (clean(r.get("kickoff_hkt")), clean(r.get("hkjc_event_id"))),
    )
    payload = {
        "phase": 3,
        "layer": 1,
        "source": "HKJC_HAD",
        "fetched_at": fetched_at,
        "request_count": 1,
        "rows": rows,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT)

    selling = sum(clean(r.get("pool_status")).upper() == "SELLINGSTARTED" for r in rows)
    identity_gaps = sum(not clean(r.get("match_id")) for r in rows)
    print(
        f"PHASE3_HKJC_CAPTURE requests=1 live_rows={len(rows)} "
        f"sellingstarted={selling} identity_gaps={identity_gaps}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
