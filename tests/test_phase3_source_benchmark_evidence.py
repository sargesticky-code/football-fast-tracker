from phase3.source_benchmark_evidence import validate_same_window_report


def _source(**overrides):
    metrics = {
        "upstream_requests": 3,
        "request_failures": 0,
        "failure_rate": 0.0,
        "median_latency_ms": 100.0,
        "p95_latency_ms": 150.0,
        "median_source_age_seconds": 4.0,
        "p95_source_age_seconds": 6.0,
        "mapped_rows": 10,
        "unmapped_rows": 0,
        "collision_rows": 0,
        "identity_match_rate": 1.0,
    }
    metrics.update(overrides)
    return metrics


def test_valid_same_window_evidence_passes():
    report = {
        "production_primary_changed": False,
        "total_upstream_requests": 6,
        "sources": {"fotmob": _source(), "sofascore": _source()},
    }
    assert validate_same_window_report(report) == []


def test_collision_and_request_count_mismatch_fail_closed():
    report = {
        "production_primary_changed": False,
        "total_upstream_requests": 7,
        "sources": {
            "fotmob": _source(),
            "sofascore": _source(collision_rows=1, identity_match_rate=0.9),
        },
    }
    errors = validate_same_window_report(report)
    assert "sofascore: identity collisions present" in errors
    assert "sofascore: identity match rate below 0.95" in errors
    assert "total upstream request count mismatch" in errors


def test_benchmark_cannot_change_production_primary():
    report = {
        "production_primary_changed": True,
        "total_upstream_requests": 6,
        "sources": {"fotmob": _source(), "sofascore": _source()},
    }
    assert "benchmark must not change production primary" in validate_same_window_report(report)
