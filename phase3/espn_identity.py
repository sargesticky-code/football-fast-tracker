"""Phase 3 Layer 2 ESPN scoreboard fallback normalizer.

Diagnostic/identity enrichment only. It cannot create HKJC eligibility.
"""
from __future__ import annotations

from datetime import datetime, timezone


def normalize_board(payload: dict) -> list[dict]:
    rows=[]
    for event in payload.get("events") or []:
        competition=(event.get("league") or {}).get("name") or ""
        comps=event.get("competitions") or []
        if not comps:
            continue
        comp=comps[0]
        competitors=comp.get("competitors") or []
        home=next((x for x in competitors if x.get("homeAway")=="home"),{})
        away=next((x for x in competitors if x.get("homeAway")=="away"),{})
        def team_name(x: dict) -> str:
            t=x.get("team") or {}
            return t.get("displayName") or t.get("shortDisplayName") or t.get("name") or ""
        rows.append({
            "id":str(event.get("id") or ""),
            "home":team_name(home),
            "away":team_name(away),
            "kickoff":str(event.get("date") or comp.get("date") or ""),
            "competition":competition or str((comp.get("type") or {}).get("text") or ""),
        })
    return [r for r in rows if r["id"] and r["home"] and r["away"]]
