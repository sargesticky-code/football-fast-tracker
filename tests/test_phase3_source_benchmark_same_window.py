from datetime import datetime, timezone

from phase3.source_latency_benchmark import Candidate, benchmark_sources


def test_two_shadow_sources_use_exact_bounded_request_count():
    calls = {"fotmob": 0, "sofascore": 0}

    def source(name):
        def fetch():
            calls[name] += 1
            return {
                "source_updated_at": "2026-09-25T00:00:00Z",
                "rows": [{"identity_status": "VERIFIED", "status": "LIVE"}],
                "unmapped_rows": 0,
                "collision_rows": 0,
            }
        return fetch

    result = benchmark_sources(
        [
            Candidate("fotmob", source("fotmob")),
            Candidate("sofascore", source("sofascore")),
        ],
        samples=3,
        now=datetime(2026, 9, 25, 0, 0, 5, tzinfo=timezone.utc),
    )

    assert calls == {"fotmob": 3, "sofascore": 3}
    assert sum(s["upstream_requests"] for s in result["sources"].values()) == 6
    assert all(s["request_failures"] == 0 for s in result["sources"].values())
    assert all(s["identity_match_rate"] == 1.0 for s in result["sources"].values())
    assert all(s["median_source_age_seconds"] == 5.0 for s in result["sources"].values())
    assert result["production_primary_changed"] is False
