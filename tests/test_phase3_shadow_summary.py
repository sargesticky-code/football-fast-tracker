from phase3.source_shadow_runner import summarize_transport_plan


def test_summary_aggregates_sources_without_promoting_primary():
    result = {
        "upstream_request_count": 6,
        "request_failures": 1,
        "traces": [
            {"source": "FotMob", "success": True, "network_latency_ms": 100, "snapshot_age_seconds": 2, "mapped_rows": 2, "unmapped_rows": 0, "collision_rows": 0},
            {"source": "SofaScore", "success": True, "network_latency_ms": 80, "snapshot_age_seconds": 4, "mapped_rows": 1, "unmapped_rows": 1, "collision_rows": 0},
            {"source": "FotMob", "success": True, "network_latency_ms": 120, "snapshot_age_seconds": 3, "mapped_rows": 2, "unmapped_rows": 0, "collision_rows": 0},
            {"source": "SofaScore", "success": False, "network_latency_ms": 90, "snapshot_age_seconds": None, "mapped_rows": 0, "unmapped_rows": 0, "collision_rows": 0},
            {"source": "FotMob", "success": True, "network_latency_ms": 110, "snapshot_age_seconds": 1, "mapped_rows": 1, "unmapped_rows": 0, "collision_rows": 0},
            {"source": "SofaScore", "success": True, "network_latency_ms": 70, "snapshot_age_seconds": 5, "mapped_rows": 1, "unmapped_rows": 0, "collision_rows": 1},
        ],
    }

    summary = summarize_transport_plan(result, eligible_rows=5)

    assert summary["mode"] == "SHADOW_ONLY"
    assert summary["production_primary_changed"] is False
    assert summary["upstream_request_count"] == 6
    assert summary["request_failures"] == 1

    fotmob = summary["sources"]["FotMob"]
    assert fotmob["upstream_requests"] == 3
    assert fotmob["request_failures"] == 0
    assert fotmob["failure_rate"] == 0
    assert fotmob["median_latency_ms"] == 110
    assert fotmob["median_snapshot_age_seconds"] == 2
    assert fotmob["mapped_rows"] == 5
    assert fotmob["identity_match_rate"] == 1
    assert fotmob["eligible_rows"] == 5
    assert fotmob["coverage_rate"] == 0.4
    assert fotmob["p95_coverage_rate"] == 0.4

    sofa = summary["sources"]["SofaScore"]
    assert sofa["upstream_requests"] == 3
    assert sofa["request_failures"] == 1
    assert sofa["failure_rate"] == 1 / 3
    assert sofa["median_latency_ms"] == 75
    assert sofa["median_snapshot_age_seconds"] == 4.5
    assert sofa["mapped_rows"] == 2
    assert sofa["unmapped_rows"] == 1
    assert sofa["collision_rows"] == 1
    assert sofa["identity_match_rate"] == 0.5
    assert sofa["eligible_rows"] == 5
    assert sofa["coverage_rate"] == 0.2
    assert sofa["p95_coverage_rate"] == 0.2
