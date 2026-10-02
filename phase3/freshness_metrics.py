"""Freshness metrics for Phase 3 live-source shadow evidence.

This module is transport-neutral: it derives score/minute age only from
provider timestamps already present in a fetched snapshot. It never performs
an upstream request or identity rematch.
"""
from statistics import median

from phase3.source_latency_benchmark import _age_seconds, _p95


def freshness_evidence(payload, observed_at):
    """Return optional source/score/minute ages for one successful snapshot."""
    payload = payload if isinstance(payload, dict) else {}
    source_updated_at = payload.get("source_updated_at")
    score_updated_at = payload.get("score_updated_at")
    minute_updated_at = payload.get("minute_updated_at")
    return {
        "source_updated_at": source_updated_at,
        "snapshot_age_seconds": _age_seconds(source_updated_at, observed_at),
        "score_updated_at": score_updated_at,
        "score_age_seconds": _age_seconds(score_updated_at, observed_at),
        "minute_updated_at": minute_updated_at,
        "minute_age_seconds": _age_seconds(minute_updated_at, observed_at),
    }


def summarize_freshness(traces):
    """Aggregate only trustworthy ages; unavailable timestamps stay unavailable."""
    score_ages = [
        float(trace["score_age_seconds"])
        for trace in traces
        if trace.get("score_age_seconds") is not None
    ]
    minute_ages = [
        float(trace["minute_age_seconds"])
        for trace in traces
        if trace.get("minute_age_seconds") is not None
    ]
    return {
        "median_score_age_seconds": median(score_ages) if score_ages else None,
        "p95_score_age_seconds": _p95(score_ages),
        "median_minute_age_seconds": median(minute_ages) if minute_ages else None,
        "p95_minute_age_seconds": _p95(minute_ages),
    }
