from phase3.source_benchmark_request_accounting import summarize_request_trace


def test_request_accounting_counts_attempts_successes_and_failures():
    trace = [
        {"source": "fotmob", "request_failed": False},
        {"source": "sofascore", "request_failed": False},
        {"source": "fotmob", "request_failed": True},
        {"source": "sofascore", "request_failed": False},
        {"source": "fotmob", "request_failed": False},
        {"source": "sofascore", "request_failed": False},
    ]

    result = summarize_request_trace(trace)

    assert result["total_upstream_requests"] == 6
    assert result["successful_upstream_requests"] == 5
    assert result["request_failures"] == 1
    assert result["sources"]["fotmob"] == {
        "upstream_requests": 3,
        "request_failures": 1,
    }
    assert result["sources"]["sofascore"] == {
        "upstream_requests": 3,
        "request_failures": 0,
    }
    assert result["production_primary_changed"] is False


def test_empty_trace_is_bounded_and_does_not_change_primary():
    result = summarize_request_trace([])

    assert result["total_upstream_requests"] == 0
    assert result["successful_upstream_requests"] == 0
    assert result["request_failures"] == 0
    assert result["sources"] == {}
    assert result["production_primary_changed"] is False
