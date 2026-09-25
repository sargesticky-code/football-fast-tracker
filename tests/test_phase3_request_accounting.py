from phase3.source_benchmark_request_accounting import summarize_request_trace


def test_request_accounting_bounded_trace():
    trace = [
        {"source": "fotmob"}, {"source": "sofascore"},
        {"source": "fotmob"}, {"source": "sofascore"},
        {"source": "fotmob"}, {"source": "sofascore"},
    ]
    report = summarize_request_trace(trace)
    assert report["total_upstream_requests"] == 6
    assert report["sources"]["fotmob"]["upstream_requests"] == 3
    assert report["sources"]["sofascore"]["upstream_requests"] == 3
    assert report["production_primary_changed"] is False
