"""Executable Phase 3 Layer 6 Heavy Lane verification probe.

Consumes a saved/current Fast Lane state JSON document and runs exactly one
bounded HeavyService cycle. It is intentionally a backend diagnostic: it does
not discover matches, fuzzy-match identities, poll, or write production state.
Only HKJC-authorised VERIFIED live rows already present in the Fast state can
reach FotMob matchDetails through HeavyCollector/HeavyLane.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from phase3.heavy_service import HeavyService


def _exit_evidence(result: Mapping[str, Any]) -> tuple[bool, str | None]:
    """Return whether this cycle proves the Layer-6 real-source exit evidence.

    This is deliberately strict: a zero-target cycle is useful fail-closed
    evidence but cannot be mistaken for real-source usable coverage. Exit
    evidence must also prove that the bounded source request actually
    succeeded and stayed inside the configured request budget.
    """
    eligible = int(result.get("eligible_rows", 0) or 0)
    source_requests = result.get("source_requests") or {}
    attempted = int(source_requests.get("attempted", 0) or 0)
    succeeded = int(source_requests.get("succeeded", 0) or 0)
    failed = int(source_requests.get("failed", 0) or 0)
    usable = int(result.get("heavy_usable_rows", 0) or 0)
    requests_used = int(result.get("requests_used", 0) or 0)
    request_budget = result.get("request_budget")
    min_interval = float(result.get("min_interval_seconds", 0) or 0)

    if eligible <= 0:
        return False, "NO_HKJC_VERIFIED_LIVE_TARGET"
    if min_interval < 30.0:
        return False, "UNSAFE_HEAVY_CADENCE"
    if attempted <= 0:
        return False, "NO_UPSTREAM_REQUEST"
    if request_budget is not None and (attempted > int(request_budget) or requests_used > int(request_budget)):
        return False, "REQUEST_BUDGET_EXCEEDED"
    if not bool(result.get("request_count_consistent", False)):
        return False, "REQUEST_COUNT_MISMATCH"
    if succeeded <= 0:
        if failed > 0:
            return False, "SOURCE_REQUEST_FAILED"
        return False, "NO_SUCCESSFUL_UPSTREAM_REQUEST"
    if usable <= 0:
        if int(result.get("detail_empty_rows", 0) or 0) > 0:
            return False, "DETAIL_EMPTY"
        if int(result.get("source_gap_rows", 0) or 0) > 0:
            return False, "SOURCE_GAP"
        if int(result.get("deferred_rows", 0) or 0) >= eligible:
            return False, "ALL_ELIGIBLE_DEFERRED"
        return False, "NO_USABLE_HEAVY_COVERAGE"
    return True, None


def run_probe(
    fast_state: Mapping[str, Any], *, now: Any = None,
    min_interval_seconds: float = 45.0,
    max_requests_per_cycle: int = 2,
    service: HeavyService | None = None,
) -> dict[str, Any]:
    """Run one source-safe Heavy Lane cycle and return audit-ready evidence."""
    heavy = service or HeavyService(
        min_interval_seconds=min_interval_seconds,
        max_requests_per_cycle=max_requests_per_cycle,
    )
    result = heavy.collect(fast_state, now=now)
    rows = result.get("heavy_rows") or []
    exit_ready, blocker = _exit_evidence(result)
    return {
        "layer": 6,
        "exit_evidence_ready": exit_ready,
        "exit_evidence_blocker": blocker,
        "fast_observed_at": result.get("fast_observed_at"),
        "heavy_observed_at": result.get("heavy_observed_at"),
        "eligible_rows": result.get("eligible_rows", 0),
        "rejected_rows": result.get("rejected_rows", 0),
        "heavy_usable_rows": result.get("heavy_usable_rows", 0),
        "detail_empty_rows": result.get("detail_empty_rows", 0),
        "source_gap_rows": result.get("source_gap_rows", 0),
        "deferred_rows": result.get("deferred_rows", 0),
        "requests_used": result.get("requests_used", 0),
        "request_budget": result.get("request_budget"),
        "source_requests": result.get("source_requests", {}),
        "request_count_consistent": result.get("request_count_consistent", False),
        "min_interval_seconds": result.get("min_interval_seconds"),
        "heavy_field_coverage": result.get("heavy_field_coverage", {}),
        "heavy_fields_observed": result.get("heavy_fields_observed", 0),
        "request_failures": result.get("request_failures", []),
        "deferred_event_ids": result.get("deferred_event_ids", []),
        "rejected_event_ids": result.get("rejected_event_ids", []),
        "observations": [
            {
                "hkjc_event_id": row.get("hkjc_event_id"),
                "external_source": row.get("external_source"),
                "external_id": row.get("external_id"),
                "heavy_status": row.get("heavy_status"),
                "heavy_observed_at": row.get("heavy_observed_at"),
                "heavy_usable_fields": row.get("heavy_usable_fields", []),
                "heavy_usable_field_count": row.get("heavy_usable_field_count", 0),
            }
            for row in rows
        ],
    }


def _load(path: str) -> Mapping[str, Any]:
    if path == "-":
        value = json.load(sys.stdin)
    else:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("fast state must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Phase 3 Heavy Lane verification cycle")
    parser.add_argument("fast_state", help="Fast-state JSON path, or - for stdin")
    parser.add_argument("--now", default=None, help="Optional ISO-8601 observation time")
    parser.add_argument("--min-interval", type=float, default=45.0)
    parser.add_argument("--request-budget", type=int, default=2)
    args = parser.parse_args(argv)
    evidence = run_probe(
        _load(args.fast_state),
        now=args.now,
        min_interval_seconds=args.min_interval,
        max_requests_per_cycle=args.request_budget,
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
