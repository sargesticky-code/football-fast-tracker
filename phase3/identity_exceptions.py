"""Durable Layer 2 unresolved-identity exception ledger.

Keeps repeated coverage/name failures observable without promoting uncertain
matches. Entries are diagnostic only and never create HKJC eligibility or an
external mapping.
"""
from __future__ import annotations

from datetime import datetime, timezone


def upsert_exception(entries: list[dict], observation: dict) -> list[dict]:
    event=str(observation.get("hkjc_event_id") or "")
    if not event:
        return entries
    now=str(observation.get("observed_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    reason=str(observation.get("reason") or "UNRESOLVED")
    providers=list(dict.fromkeys(str(x) for x in (observation.get("providers_tried") or []) if x))
    out=[dict(x) for x in entries]
    for row in out:
        if str(row.get("hkjc_event_id") or "")==event:
            row["last_seen_at"]=now
            row["observations"]=int(row.get("observations") or 0)+1
            row["reason"]=reason
            row["providers_tried"]=providers
            row["home"]=observation.get("home") or row.get("home") or ""
            row["away"]=observation.get("away") or row.get("away") or ""
            return out
    out.append({
        "hkjc_event_id":event,
        "home":str(observation.get("home") or ""),
        "away":str(observation.get("away") or ""),
        "reason":reason,
        "providers_tried":providers,
        "first_seen_at":now,
        "last_seen_at":now,
        "observations":1,
    })
    return out


def prune_exceptions(entries: list[dict], active_event_ids: set[str], terminal_event_ids: set[str] | None=None) -> list[dict]:
    """Retain active unresolved rows and explicit terminal history only."""
    terminal_event_ids=terminal_event_ids or set()
    keep=active_event_ids | terminal_event_ids
    return [dict(x) for x in entries if str(x.get("hkjc_event_id") or "") in keep]
