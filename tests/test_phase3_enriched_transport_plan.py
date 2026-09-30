from datetime import datetime, timezone

from phase3.source_latency_benchmark import Candidate
from phase3.source_shadow_runner import execute_transport_plan, interleaved_request_plan


def test_enriched_plan_preserves_one_call_per_slot_and_identity_evidence():
    calls = {"fotmob": 0, "sofascore": 0}

    def fetch(name):
        def _fetch():
            calls[name] += 1
            return {
                "source_updated_at": "2026-09-30T01:00:00+00:00",
                "rows": [
                    {"identity_status": "VERIFIED"},
                    {"identity_status": "FUZZY"},
                ],
                "unmapped_rows": 1,
                "collision_rows": 0,
            }
        return _fetch

    candidates = [
        Candidate("fotmob", fetch("fotmob")),
        Candidate("sofascore", fetch("sofascore")),
    ]
    plan = interleaved_request_plan(candidates, rounds=3)
    result = execute_transport_plan(
        plan,
        enrich=True,
        now=datetime(2026, 9, 30, 1, 0, 5, tzinfo=timezone.utc),
    )

    assert result["upstream_request_count"] == 6
    assert result["request_failures"] == 0
    assert calls == {"fotmob": 3, "sofascore": 3}
    assert [trace["mapped_rows"] for trace in result["traces"]] == [1] * 6
    assert [trace["unmapped_rows"] for trace in result["traces"]] == [1] * 6
    assert [trace["collision_rows"] for trace in result["traces"]] == [0] * 6
    assert [trace["snapshot_age_seconds"] for trace in result["traces"]] == [5.0] * 6
