"""Phase 3 Layer 5 consumer projection for the shared fast heartbeat.

This module is deliberately read-only. It converts Layer-3/4 shared state into
an explicit dashboard/API contract without importing Phase 1/2 logic or
writing to the production Google Sheet.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


def _identity_state(state: Mapping[str, Any]) -> str:
    """Collapse Layer-3 identity diagnostics into a fail-closed UI state.

    Layer 3 has emitted collision diagnostics under both count fields and
    explicit duplicate-ID collections over time.  Treat any of those forms as
    an identity gap so a consumer can never render a colliding observation as
    a verified match merely because the diagnostic representation changed.
    """
    collision_count = int(state.get("collision_count") or 0)
    duplicate_external_ids = state.get("duplicate_external_ids") or []
    duplicate_observation_ids = state.get("duplicate_observation_ids") or []
    has_collision = bool(collision_count or duplicate_external_ids or duplicate_observation_ids)
    unmapped = int(state.get("unmapped_count") or 0)
    missing = state.get("missing_target_ids") or []
    if has_collision:
        return "IDENTITY_GAP"
    if unmapped or missing:
        return "UNMAPPED"
    return "MAPPED"


def _display_state(state: Mapping[str, Any]) -> str:
    health = str(state.get("health") or "NO_FAST_SNAPSHOT")
    identity = _identity_state(state)
    if health == "REQUEST_FAILED":
        return "REQUEST_FAILED"
    if health in {"STALE_FAST_SNAPSHOT", "NO_FAST_SNAPSHOT"}:
        return "STALE"
    if identity == "IDENTITY_GAP":
        return "IDENTITY_GAP"
    if identity == "UNMAPPED":
        return "UNMAPPED"
    if health == "FRESH_LIVE":
        return "FRESH"
    return "NO_LIVE"


def project_fast_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable, fail-closed consumer contract for Layer 5 surfaces."""
    rows = state.get("rows") or state.get("joined_rows") or []
    if not isinstance(rows, list):
        rows = []
    shared = state.get("shared_cache") if isinstance(state.get("shared_cache"), Mapping) else {}
    return {
        "display_state": _display_state(state),
        "health": state.get("health") or "NO_FAST_SNAPSHOT",
        "observed_at": state.get("observed_at"),
        "snapshot_age_seconds": state.get("snapshot_age_seconds"),
        "request_failures": int(state.get("request_failures") or 0),
        "mapped_rows": int(state.get("mapped_rows") or 0),
        "live_rows": int(state.get("live_rows") or 0),
        "unmapped_count": int(state.get("unmapped_count") or 0),
        "unmapped_external_ids": list(state.get("unmapped_external_ids") or []),
        "missing_target_ids": list(state.get("missing_target_ids") or []),
        "identity_state": _identity_state(state),
        "last_good_at": state.get("last_good_at"),
        "last_good_age_seconds": state.get("last_good_age_seconds"),
        "shared_cache": {
            "status": shared.get("status"),
            "lease_age_seconds": shared.get("lease_age_seconds"),
            "upstream_refreshes": shared.get("upstream_refreshes"),
        },
        "matches": deepcopy(rows),
    }
