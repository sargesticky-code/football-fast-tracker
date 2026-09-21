"""Durable Layer 2 unresolved-identity exception ledger.

Keeps repeated coverage/name failures observable without promoting uncertain
matches. Entries are diagnostic only and never create HKJC eligibility or an
external mapping. Verified mappings resolve, rather than erase, prior
exceptions so terminal history remains auditable.
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
            row["status"]="ACTIVE"
            row.pop("resolved_at",None); row.pop("resolved_source",None); row.pop("resolved_source_match_id",None)
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
        "status":"ACTIVE",
    })
    return out


def resolve_verified_exceptions(entries: list[dict], registry_rows: list[dict], resolved_at: str | None=None) -> list[dict]:
    """Mark exceptions RESOLVED only when the durable registry says VERIFIED."""
    now=resolved_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    verified={str(r.get("hkjc_event_id") or ""):r for r in registry_rows if r.get("status")=="VERIFIED" and r.get("hkjc_event_id")}
    out=[]
    for item in entries:
        row=dict(item); match=verified.get(str(row.get("hkjc_event_id") or ""))
        if match:
            row["status"]="RESOLVED"; row["resolved_at"]=now
            row["resolved_source"]=str(match.get("source") or "")
            row["resolved_source_match_id"]=str(match.get("source_match_id") or "")
        out.append(row)
    return out


def prune_exceptions(entries: list[dict], active_event_ids: set[str], terminal_event_ids: set[str] | None=None) -> list[dict]:
    """Retain active unresolved rows and explicit terminal history only."""
    terminal_event_ids=terminal_event_ids or set()
    keep=active_event_ids | terminal_event_ids
    return [dict(x) for x in entries if str(x.get("hkjc_event_id") or "") in keep]
