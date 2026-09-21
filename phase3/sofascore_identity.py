"""Phase 3 Layer 2 Sofascore fallback board parser.

This module only normalizes scheduled-event board data. HKJC remains the sole
live-eligibility authority and candidate promotion remains in identity_registry.
"""
from __future__ import annotations

from datetime import datetime, timezone


def normalize_board(payload: dict) -> list[dict]:
    rows=[]
    for event in payload.get("events") or []:
        home=event.get("homeTeam") or {}
        away=event.get("awayTeam") or {}
        tournament=(event.get("tournament") or {}).get("name") or ""
        ts=event.get("startTimestamp")
        kickoff=""
        if isinstance(ts,(int,float)):
            kickoff=datetime.fromtimestamp(ts,tz=timezone.utc).isoformat()
        rows.append({
            "id":event.get("id"),
            "home":home.get("name") or home.get("shortName") or "",
            "away":away.get("name") or away.get("shortName") or "",
            "kickoff":kickoff,
            "competition":tournament,
        })
    return [r for r in rows if r["id"]]
