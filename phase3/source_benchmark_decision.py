"""Fail-closed decision gate for Phase 3 live-source shadow benchmarks.

This module never changes the production source. It only decides whether a
same-window benchmark contains enough evidence to justify considering a
candidate for promotion. HKJC eligibility and persistent VERIFIED identity
remain upstream requirements.
"""
from __future__ import annotations

from typing import Any, Mapping


def assess_candidate(
    benchmark: Mapping[str, Any],
    *,
    baseline: str,
    candidate: str,
    min_samples: int = 3,
    max_failure_rate: float = 0.05,
    min_identity_match_rate: float = 0.95,
) -> dict[str, Any]:
    sources = benchmark.get("sources") or {}
    base = sources.get(baseline)
    challenger = sources.get(candidate)
    blockers: list[str] = []

    if benchmark.get("mode") != "SHADOW_ONLY":
        blockers.append("NOT_SHADOW_BENCHMARK")
    if not isinstance(base, Mapping) or not isinstance(challenger, Mapping):
        blockers.append("MISSING_SOURCE")
        return {"promotion_ready": False, "blockers": blockers}

    for name, source in ((baseline, base), (candidate, challenger)):
        if int(source.get("samples") or 0) < min_samples:
            blockers.append(f"{name}:INSUFFICIENT_SAMPLES")
        if float(source.get("failure_rate") or 0.0) > max_failure_rate:
            blockers.append(f"{name}:FAILURE_RATE")
        match_rate = source.get("identity_match_rate")
        if match_rate is None or float(match_rate) < min_identity_match_rate:
            blockers.append(f"{name}:IDENTITY_COVERAGE")
        if source.get("median_latency_ms") is None or source.get("p95_latency_ms") is None:
            blockers.append(f"{name}:LATENCY_MISSING")
        if source.get("median_source_age_seconds") is None:
            blockers.append(f"{name}:SOURCE_AGE_MISSING")

    if blockers:
        return {"promotion_ready": False, "blockers": blockers}

    if not (
        float(challenger["median_latency_ms"]) < float(base["median_latency_ms"])
        and float(challenger["p95_latency_ms"]) < float(base["p95_latency_ms"])
    ):
        blockers.append("CANDIDATE_NOT_CONSISTENTLY_FASTER")
    if float(challenger["median_source_age_seconds"]) > float(base["median_source_age_seconds"]):
        blockers.append("CANDIDATE_DATA_STALER")

    return {
        "promotion_ready": not blockers,
        "blockers": blockers,
        "baseline": baseline,
        "candidate": candidate,
        "production_primary_changed": False,
    }
