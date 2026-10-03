from phase3.source_shadow_runner import summarize_transport_plan


def test_shadow_summary_reports_score_and_minute_freshness_without_extra_requests():
    result = {
        "upstream_request_count": 2,
        "request_failures": 0,
        "traces": [
            {
                "source": "fotmob",
                "success": True,
                "network_latency_ms": 80,
                "snapshot_age_seconds": 3,
                "score_age_seconds": 4,
                "minute_age_seconds": 7,
                "mapped_rows": 1,
                "unmapped_rows": 0,
                "collision_rows": 0,
            },
            {
                "source": "fotmob",
                "success": True,
                "network_latency_ms": 120,
                "snapshot_age_seconds": 5,
                "score_age_seconds": 8,
                "minute_age_seconds": 11,
                "mapped_rows": 1,
                "unmapped_rows": 0,
                "collision_rows": 0,
            },
        ],
    }

    summary = summarize_transport_plan(result, eligible_rows=1)
    source = summary["sources"]["fotmob"]

    assert summary["upstream_request_count"] == 2
    assert source["upstream_requests"] == 2
    assert source["median_score_age_seconds"] == 6.0
    assert source["p95_score_age_seconds"] == 8.0
    assert source["median_minute_age_seconds"] == 9.0
    assert source["p95_minute_age_seconds"] == 11.0


def test_shadow_summary_keeps_missing_freshness_unavailable():
    result = {
        "upstream_request_count": 1,
        "request_failures": 0,
        "traces": [
            {
                "source": "sofascore",
                "success": True,
                "network_latency_ms": 90,
                "mapped_rows": 1,
                "unmapped_rows": 0,
                "collision_rows": 0,
            }
        ],
    }

    source = summarize_transport_plan(result, eligible_rows=1)["sources"]["sofascore"]

    assert source["median_score_age_seconds"] is None
    assert source["p95_score_age_seconds"] is None
    assert source["median_minute_age_seconds"] is None
    assert source["p95_minute_age_seconds"] is None
