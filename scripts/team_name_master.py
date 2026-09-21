from __future__ import annotations

import os
from typing import Callable

import requests

TEAM_NAME_MASTER_URL = os.getenv(
    "TEAM_NAME_MASTER_URL",
    "https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/team-name-master",
).strip()
TIMEOUT = 12


_CACHE: dict[str, dict] = {}

def fetch_master_payload(source: str) -> dict:
    source = (source or "").strip().upper()
    if not source:
        return {"rows": [], "blockedNames": []}
    if source in _CACHE:
        return _CACHE[source]
    try:
        r = requests.get(
            TEAM_NAME_MASTER_URL,
            params={"source": source},
            headers={"Accept": "application/json", "User-Agent": "football-fast-tracker/1.0"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        payload = r.json() or {}
        if payload.get("ok") is not True:
            payload = {"rows": [], "blockedNames": []}
    except Exception as exc:
        print(f"WARNING team-name-master source={source} unavailable: {exc}", flush=True)
        payload = {"rows": [], "blockedNames": []}
    _CACHE[source] = payload
    return payload


def fetch_verified_rows(source: str) -> list[dict]:
    rows = fetch_master_payload(source).get("rows")
    return rows if isinstance(rows, list) else []


def build_forward_map(source: str, normalizer: Callable[[str], str]) -> dict[str, str]:
    """source/global team name -> canonical HKJC English name.

    Source-specific verified rows win. If a source has never seen a name before,
    the globally unique cross-source dictionary can still resolve it. Any local
    normalizer collision is dropped rather than guessed.
    """
    source_payload = fetch_master_payload(source)
    source_rows = source_payload.get("rows") if isinstance(source_payload.get("rows"), list) else []
    blocked_names = source_payload.get("blockedNames") if isinstance(source_payload.get("blockedNames"), list) else []
    global_rows = fetch_verified_rows("GLOBAL")
    out: dict[str, str] = {}
    bad: set[str] = set()
    blocked = {normalizer(str(name)) for name in blocked_names if normalizer(str(name))}

    def add(rows: list[dict], *, override: bool, skip_blocked: bool = False) -> None:
        for row in rows:
            source_name = str(row.get("source_name") or "").strip()
            canonical = str(row.get("hkjc_name_en") or "").strip()
            key = normalizer(source_name)
            if not key or not canonical:
                continue
            if skip_blocked and key in blocked:
                continue
            old = out.get(key)
            if old and old != canonical and not override:
                bad.add(key)
                continue
            if override or key not in out:
                out[key] = canonical

    # Global reuse is allowed only for names the current source has never
    # classified as candidate/ambiguous. Source-specific verified mapping wins.
    add(global_rows, override=False, skip_blocked=True)
    for key in bad:
        out.pop(key, None)
    add(source_rows, override=True)

    print(
        f"TEAM_NAME_MASTER source={source.upper()} source_rows={len(source_rows)} "
        f"global_rows={len(global_rows)} blocked={len(blocked)} "
        f"usable_forward={len(out)} local_collisions={len(bad)}",
        flush=True,
    )
    return out


def build_reverse_map(source: str, normalizer: Callable[[str], str]) -> dict[str, str]:
    """canonical HKJC English name -> preferred source team name."""
    chosen: dict[str, tuple[tuple[float, int, str], str]] = {}
    rows = fetch_verified_rows(source)
    for row in rows:
        source_name = str(row.get("source_name") or "").strip()
        canonical = str(row.get("hkjc_name_en") or "").strip()
        key = normalizer(canonical)
        if not key or not source_name:
            continue
        try:
            confidence = float(row.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        try:
            events = int(row.get("event_count") or 0)
        except (TypeError, ValueError):
            events = 0
        last_seen = str(row.get("last_seen_at") or "")
        rank = (confidence, events, last_seen)
        old = chosen.get(key)
        if old is None or rank > old[0]:
            chosen[key] = (rank, source_name)
    out = {k: v[1] for k, v in chosen.items()}
    print(
        f"TEAM_NAME_MASTER source={source.upper()} verified_rows={len(rows)} "
        f"usable_reverse={len(out)}",
        flush=True,
    )
    return out
