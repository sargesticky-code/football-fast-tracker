from datetime import datetime, timezone

from phase3.source_latency_benchmark import Candidate, benchmark_sources


def test_shadow_benchmark_keeps_source_selection_unchanged_and_counts_identity_health():
    def fotmob():
        return {
            "source_updated_at": "2026-09-24T14:00:00Z",
            "rows": [
                {"identity_status": "VERIFIED", "status": "LIVE"},
                {"identity_status": "VERIFIED", "status": "FINISHED"},
            ],
            "unmapped_rows": 1,
            "collision_rows": 1,
        }

    result = benchmark_sources(
        [Candidate("fotmob", fotmob)], samples=2,
        now=datetime(2026, 9, 24, 14, 0, 5, tzinfo=timezone.utc),
    )
    source = result["sources"]["fotmob"]
    assert result["mode"] == "SHADOW_ONLY"
    assert result["production_primary_changed"] is False
    assert source["upstream_requests"] == 2
    assert source["request_failures"] == 0
    assert source["mapped_rows"] == 4
    assert source["unmapped_rows"] == 2
    assert source["collision_rows"] == 2
    assert source["live_rows"] == 2
    assert source["identity_match_rate"] == .5
    assert source["median_source_age_seconds"] == 5.0
    assert source["median_latency_ms"] is not None
    assert source["p95_latency_ms"] is not None


def test_failure_is_isolated_per_candidate_and_counted():
    calls = {"bad": 0, "good": 0}

    def bad():
        calls["bad"] += 1
        raise RuntimeError("temporary source failure")

    def good():
        calls["good"] += 1
        return {"rows": [{"identity_status": "VERIFIED", "status": "IN_PLAY"}]}

    result = benchmark_sources(
        [Candidate("regional", bad), Candidate("fotmob", good)], samples=3,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    assert calls == {"bad": 3, "good": 3}
    assert result["sources"]["regional"]["failure_rate"] == 1.0
    assert result["sources"]["regional"]["median_latency_ms"] is None
    assert result["sources"]["fotmob"]["failure_rate"] == 0.0
    assert result["sources"]["fotmob"]["mapped_rows"] == 3


def test_invalid_sample_count_fails_closed():
    try:
        benchmark_sources([], samples=0)
    except ValueError as exc:
        assert "samples" in str(exc)
    else:
        raise AssertionError("expected ValueError")
