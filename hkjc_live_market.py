"""One-request HKJC in-play market capture for Fast Tracker.

The HKJC frontend's exact whitelisted MATCH_ODDS query is vendored separately.
For a small list of already-known HKJC front-end IDs, one INPLAY_ALL GraphQL
request returns all active in-play pools. This module extracts HAD, HIL and CHL
without any per-market or per-match fan-out.

It is deliberately fail-soft and cached in-process. Callers must preserve
last-good snapshots externally if the process is cold and HKJC blocks/errors.
"""
from __future__ import annotations

import math
import os
import time
from typing import Any

import requests

from vendor_hkjc_queries import MATCH_ODDS

ENDPOINT = "https://info.cld.hkjc.com/graphql/base/"
MIN_REFRESH_SECONDS = max(60, int(os.getenv("HKJC_LIVE_MARKET_REFRESH_SECONDS", "90")))
TIMEOUT = max(3, int(os.getenv("HKJC_LIVE_MARKET_TIMEOUT_SECONDS", "8")))

INPLAY_ALL = [
    "HAD", "EHA", "CHP", "TQL", "FHA", "HHA", "HDC", "EDC", "HIL", "EHL",
    "FHL", "CHL", "ECH", "FCH", "CRS", "ECS", "FCS", "AGS", "NGS", "FTS",
    "TTG", "ETG", "NTS", "ENT", "FHH", "FHC", "CHD", "ECD", "EHH", "HLH",
    "HLA", "FLH", "FLA", "ELH", "ELA", "CHH", "CHA", "CFH", "CFA", "CEH",
    "CEA",
]
TARGET_TYPES = {"HAD", "HIL", "CHL"}

_CACHE: dict[str, Any] = {
    "key": (),
    "fetched_at": 0.0,
    "markets": {},
    "health": "EMPTY",
}


def _headers():
    return {
        "Content-Type": "application/json",
        "Origin": "https://bet.hkjc.com",
        "Referer": "https://bet.hkjc.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
    }


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def _float(v):
    try:
        x = float(v)
        return x if math.isfinite(x) and x > 1.0 else None
    except (TypeError, ValueError):
        return None


def _fair(odds: dict[str, float]) -> dict[str, float]:
    if not odds or any(v <= 1 for v in odds.values()):
        return {}
    inv = {k: 1.0 / v for k, v in odds.items()}
    total = sum(inv.values())
    if total <= 0:
        return {}
    return {k: round(v / total, 6) for k, v in inv.items()}


def _line_record(line: dict) -> dict:
    odds = {}
    selections = []
    for comb in line.get("combinations") or []:
        sel = _clean(comb.get("str")).upper()
        price = _float(comb.get("currentOdds"))
        selections.append({
            "selection": sel,
            "odds": price,
            "status": _clean(comb.get("status")),
            "comb_id": _clean(comb.get("combId")),
        })
        if sel and price is not None:
            odds[sel] = price
    return {
        "line_id": _clean(line.get("lineId")),
        "status": _clean(line.get("status")),
        "condition": _clean(line.get("condition")),
        "main": bool(line.get("main")),
        "selections": selections,
        "fair": _fair(odds),
    }


def _pool_record(pool: dict) -> dict:
    lines = [_line_record(x) for x in (pool.get("lines") or [])]
    main = next((x for x in lines if x.get("main")), None)
    if main is None and lines:
        main = lines[0]
    return {
        "odds_type": _clean(pool.get("oddsType")).upper(),
        "pool_id": _clean(pool.get("id")),
        "status": _clean(pool.get("status")),
        "inplay": bool(pool.get("inplay")),
        "updated_at": _clean(pool.get("updateAt")),
        "expected_suspend_at": _clean(pool.get("expectedSuspendDateTime")),
        "main_line": main,
        "lines": lines,
    }


def _normalize(matches: list[dict]) -> dict[str, dict]:
    out = {}
    for match in matches or []:
        event_id = _clean(match.get("frontEndId"))
        if not event_id:
            continue
        pools = {}
        latest = ""
        for pool in match.get("foPools") or []:
            odds_type = _clean(pool.get("oddsType")).upper()
            if odds_type not in TARGET_TYPES:
                continue
            rec = _pool_record(pool)
            pools[odds_type] = rec
            if rec["updated_at"] > latest:
                latest = rec["updated_at"]

        running = match.get("runningResult") or {}
        running_extra = match.get("runningResultExtra") or {}
        out[event_id] = {
            "hkjc_event_id": event_id,
            "match_id": _clean(match.get("id")),
            "status": _clean(match.get("status")),
            "updated_at": latest or _clean(match.get("updateAt")),
            "home_score": running.get("homeScore", running_extra.get("homeScore")),
            "away_score": running.get("awayScore", running_extra.get("awayScore")),
            "home_corners": running.get("homeCorner", running_extra.get("homeCorner")),
            "away_corners": running.get("awayCorner", running_extra.get("awayCorner")),
            "HAD": pools.get("HAD"),
            "HIL": pools.get("HIL"),
            "CHL": pools.get("CHL"),
        }
    return out


def _variables(front_end_ids: list[str]) -> dict:
    return {
        "fbOddsTypes": INPLAY_ALL,
        "fbOddsTypesM": INPLAY_ALL,
        "inplayOnly": True,
        "featuredMatchesOnly": False,
        "startDate": None,
        "endDate": None,
        "tournIds": None,
        "matchIds": None,
        "tournId": None,
        "tournProfileId": None,
        "subType": None,
        "startIndex": None,
        "endIndex": None,
        "frontEndIds": front_end_ids,
        "earlySettlementOnly": False,
        "showAllMatch": False,
        "tday": None,
        "tIdList": None,
    }


def fetch_live_markets(event_ids: list[str]) -> tuple[dict[str, dict], dict]:
    ids = tuple(sorted({_clean(x) for x in event_ids if _clean(x)}))
    if not ids:
        return {}, {
            "status": "NO_LIVE_TARGETS",
            "request_count": 0,
            "cache_hit": False,
            "refresh_seconds": MIN_REFRESH_SECONDS,
        }

    now = time.time()
    if (
        _CACHE.get("key") == ids
        and now - float(_CACHE.get("fetched_at") or 0) < MIN_REFRESH_SECONDS
    ):
        return dict(_CACHE.get("markets") or {}), {
            "status": _CACHE.get("health") or "CACHE",
            "request_count": 0,
            "cache_hit": True,
            "refresh_seconds": MIN_REFRESH_SECONDS,
        }

    payload = {"query": MATCH_ODDS, "variables": _variables(list(ids))}
    try:
        res = requests.post(
            ENDPOINT,
            json=payload,
            headers=_headers(),
            timeout=TIMEOUT,
        )
        if res.status_code in (403, 429):
            raise requests.HTTPError(
                f"HKJC HTTP {res.status_code}",
                response=res,
            )
        res.raise_for_status()
        body = res.json()
        errors = body.get("errors") or []
        if errors:
            message = "; ".join(_clean(x.get("message")) for x in errors)
            raise RuntimeError("HKJC GraphQL: " + message)

        markets = _normalize(((body.get("data") or {}).get("matches") or []))
        health = "OK" if markets else "OK_NO_INPLAY_MARKETS"
        _CACHE.update({
            "key": ids,
            "fetched_at": now,
            "markets": markets,
            "health": health,
        })
        return markets, {
            "status": health,
            "request_count": 1,
            "cache_hit": False,
            "refresh_seconds": MIN_REFRESH_SECONDS,
            "queried_event_ids": len(ids),
            "returned_event_ids": len(markets),
        }
    except Exception as exc:
        stale = (
            _CACHE.get("key") == ids
            and bool(_CACHE.get("markets"))
        )
        if stale:
            return dict(_CACHE.get("markets") or {}), {
                "status": "STALE_LAST_GOOD:" + type(exc).__name__,
                "request_count": 1,
                "cache_hit": True,
                "refresh_seconds": MIN_REFRESH_SECONDS,
                "queried_event_ids": len(ids),
                "returned_event_ids": len(_CACHE.get("markets") or {}),
            }
        return {}, {
            "status": "ERROR:" + type(exc).__name__,
            "request_count": 1,
            "cache_hit": False,
            "refresh_seconds": MIN_REFRESH_SECONDS,
            "queried_event_ids": len(ids),
            "returned_event_ids": 0,
        }
