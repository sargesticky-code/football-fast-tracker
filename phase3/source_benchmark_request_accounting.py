"""Phase 3 benchmark request accounting helpers."""


def summarize_request_trace(trace):
    """Summarize bounded shadow requests without changing source priority."""
    per_source = {}
    failures = 0
    for item in trace:
        name = item["source"]
        bucket = per_source.setdefault(name, {"upstream_requests": 0, "request_failures": 0})
        bucket["upstream_requests"] += 1
        if item.get("request_failed"):
            bucket["request_failures"] += 1
            failures += 1
    return {
        "total_upstream_requests": len(trace),
        "request_failures": failures,
        "sources": per_source,
        "successful_upstream_requests": len(trace) - failures,
        "production_primary_changed": False,
    }
