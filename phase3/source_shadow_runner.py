from datetime import datetime, timezone
from time import perf_counter

from phase3.source_latency_benchmark import Candidate


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


def execute_transport_plan(plan):
    """Execute a bounded shadow plan sequentially and account for upstream calls."""
    traces = []
    for slot in plan:
        traces.append(execute_transport_slot(slot))
    return {
        "traces": traces,
        "upstream_request_count": len(traces),
        "request_failures": sum(not trace["success"] for trace in traces),
    }
