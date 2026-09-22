"""Phase 3 Layer 2 persistent-state continuity guards.

These invariants detect cache/evidence loss without promoting or fabricating an
external identity. They are intentionally independent of Phase 1/2 logic.
"""
from __future__ import annotations


def registry_fingerprint(rows: list[dict]) -> dict:
    candidates = {
        (str(r.get("hkjc_event_id")), str(r.get("source")), str(r.get("source_match_id"))): (
            int(r.get("evidence_count") or 0), float(r.get("evidence_span_seconds") or 0.0)
        )
        for r in rows if r.get("status") == "CANDIDATE"
    }
    verified = {
        (str(r.get("hkjc_event_id")), str(r.get("source")), str(r.get("source_match_id")))
        for r in rows if r.get("status") == "VERIFIED"
    }
    return {"candidates": candidates, "verified": verified}


def assert_empty_cycle_retention(before: dict, after: dict) -> None:
    """An empty HKJC-eligible cycle must not erase prior identity progress."""
    missing_verified = before["verified"] - after["verified"]
    if missing_verified:
        raise AssertionError(f"verified identity disappeared: {sorted(missing_verified)}")
    for key, (count, span) in before["candidates"].items():
        current = after["candidates"].get(key)
        # Promotion is a valid transition; disappearance is not.
        if key in after["verified"]:
            continue
        if current is None:
            raise AssertionError(f"candidate identity disappeared: {key}")
        if current[0] < count or current[1] < span:
            raise AssertionError(
                f"candidate evidence regressed: {key} before={(count, span)} after={current}"
            )
