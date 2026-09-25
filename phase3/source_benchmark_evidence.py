"""Phase 3 same-window benchmark evidence validator.

Pure diagnostic: validates saved benchmark reports without making network calls
or changing production source priority.
"""
from __future__ import annotations

from typing import Any


REQUIRED_SOURCE_FIELDS = {
    "upstream_requests",
    "request_failures",
    "failure_rate",
    "median_latency_ms",
    "p95_latency_ms",
    "median_source_age_seconds",
    "p95_source_age_seconds",
    "mapped_rows",
    "unmapped_rows",
    "collision_rows",
    "identity_match_rate",
}


def validate_same_window_report(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("production_primary_changed") is not False:
        errors.append("benchmark must not change production primary")
    sources = report.get("sources") or {}
    if len(sources) < 2:
        errors.append("at least two sources required")
    for name, metrics in sources.items():
        missing = sorted(REQUIRED_SOURCE_FIELDS - set(metrics))
        if missing:
            errors.append(f"{name}: missing fields: {','.join(missing)}")
        if metrics.get("collision_rows", 0):
            errors.append(f"{name}: identity collisions present")
        rate = metrics.get("identity_match_rate")
        if rate is None or rate < 0.95:
            errors.append(f"{name}: identity match rate below 0.95")
    total = report.get("total_upstream_requests")
    if total is not None:
        measured = sum(int(m.get("upstream_requests", 0) or 0) for m in sources.values())
        if total != measured:
            errors.append("total upstream request count mismatch")
    return errors
