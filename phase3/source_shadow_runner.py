from datetime import datetime, timezone
from statistics import median
from time import perf_counter

from phase3.source_latency_benchmark import Candidate, _age_seconds, _p95


def interleaved_request_order(candidates, rounds=3):
    if rounds < 1:
        raise ValueError("rounds must be >= 1")
    names = [candidate.name for candidate in candidates]
    if len(names) < 2:
        raise ValueError("at least two sources required")
    return names * rounds


def interleaved_request_plan(candidates, rounds=3):
    """Return bounded sequential source slots for a same-window shadow run."""
    candidates = list(candidates)
    order = interleaved_request_order(candidates, rounds=rounds)
    by_name = {candidate.name: candidate for candidate in candidates}
    return [
        {"sequence": sequence, "source": name, "candidate": by_name[name]}
        for sequence, name in enumerate(order, start=1)
    ]


def execute_transport_slot(slot):
    """Execute one shadow slot exactly once and return transport-only evidence."""
    observed_at = datetime.now(timezone.utc).isoformat()
    started = perf_counter()
    try:
        payload = slot["candidate"].fetch()
    except Exception as exc:
        return {
            "sequence": slot["sequence"],
            "source": slot["source"],
            "observed_at": observed_at,
            "network_latency_ms": round((perf_counter() - started) * 1000, 3),
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "payload": None,
        }
    return {
        "sequence": slot["sequence"],
        "source": slot["source"],
        "observed_at": observed_at,
        "network_latency_ms": round((perf_counter() - started) * 1000, 3),
        "success": True,
        "error": None,
        "payload": payload,
    }


def execute_transport_plan(plan, *, enrich=False, now=None):
    """Execute a bounded shadow plan sequentially and account for upstream calls.

    When ``enrich`` is enabled, each trace also carries source freshness and
    persistent VERIFIED identity evidence. This remains transport-only: it
    never performs fuzzy rematching or extra upstream requests.
    """
    traces = []
    for slot in plan:
        trace = execute_transport_slot(slot)
        if enrich:
            trace = enrich_transport_trace(trace, now=now)
        traces.append(trace)
    return {
        "traces": traces,
        "upstream_request_count": len(traces),
        "request_failures": sum(not trace["success"] for trace in traces),
    }


def enrich_transport_trace(trace, *, now=None):
    """Add freshness and persistent-identity evidence without fuzzy rematching."""
    enriched = dict(trace)
    payload = enriched.get("payload") if enriched.get("success") else None
    payload = payload if isinstance(payload, dict) else {}
    clock = now or datetime.now(timezone.utc)
    source_updated_at = payload.get("source_updated_at")
    rows = payload.get("rows") or []

    mapped = sum(
        1 for row in rows
        if isinstance(row, dict) and row.get("identity_status") == "VERIFIED"
    )
    unmapped = int(payload.get("unmapped_rows", 0) or 0)
    collisions = int(payload.get("collision_rows", 0) or 0)

    enriched.update({
        "source_updated_at": source_updated_at,
        "snapshot_age_seconds": _age_seconds(source_updated_at, clock),
        "mapped_rows": mapped,
        "unmapped_rows": unmapped,
        "collision_rows": collisions,
    })
    return enriched


def summarize_transport_plan(result):
    """Aggregate bounded shadow traces per source without changing source priority."""
    summaries = {}
    for trace in result.get("traces", []):
        source = trace["source"]
        summary = summaries.setdefault(source, {
            "upstream_requests": 0,
            "request_failures": 0,
            "latencies_ms": [],
            "snapshot_ages_seconds": [],
            "mapped_rows": 0,
            "unmapped_rows": 0,
            "collision_rows": 0,
        })
        summary["upstream_requests"] += 1
        summary["request_failures"] += int(not trace.get("success", False))
        if trace.get("success") and trace.get("network_latency_ms") is not None:
            summary["latencies_ms"].append(float(trace["network_latency_ms"]))
        if trace.get("snapshot_age_seconds") is not None:
            summary["snapshot_ages_seconds"].append(float(trace["snapshot_age_seconds"]))
        summary["mapped_rows"] += int(trace.get("mapped_rows", 0) or 0)
        summary["unmapped_rows"] += int(trace.get("unmapped_rows", 0) or 0)
        summary["collision_rows"] += int(trace.get("collision_rows", 0) or 0)

    output = {}
    for source, summary in summaries.items():
        requests = summary["upstream_requests"]
        identities = summary["mapped_rows"] + summary["unmapped_rows"] + summary["collision_rows"]
        latencies = summary.pop("latencies_ms")
        ages = summary.pop("snapshot_ages_seconds")
        output[source] = {
            **summary,
            "failure_rate": summary["request_failures"] / requests if requests else 0.0,
            "median_latency_ms": median(latencies) if latencies else None,
            "p95_latency_ms": _p95(latencies),
            "median_snapshot_age_seconds": median(ages) if ages else None,
            "p95_snapshot_age_seconds": _p95(ages),
            "identity_match_rate": summary["mapped_rows"] / identities if identities else None,
        }
    return {
        "mode": "SHADOW_ONLY",
        "production_primary_changed": False,
        "upstream_request_count": result.get("upstream_request_count", 0),
        "request_failures": result.get("request_failures", 0),
        "sources": output,
    }
