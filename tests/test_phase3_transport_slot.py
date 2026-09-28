from phase3.source_latency_benchmark import Candidate
from phase3.source_shadow_runner import (
    execute_transport_plan,
    execute_transport_slot,
    interleaved_request_plan,
)


def test_transport_slot_records_success_once():
    calls = []
    candidate = Candidate(name="fotmob", fetch=lambda: calls.append(1) or {"ok": True})
    trace = execute_transport_slot({"sequence": 1, "source": "fotmob", "candidate": candidate})
    assert calls == [1]
    assert trace["success"] is True
    assert trace["payload"] == {"ok": True}
    assert trace["error"] is None
    assert trace["observed_at"]
    assert trace["network_latency_ms"] >= 0


def test_transport_plan_accounts_for_six_calls_and_mixed_failures():
    calls = []

    def fotmob_fetch():
        calls.append("fotmob")
        return {"ok": True}

    def sofascore_fetch():
        calls.append("sofascore")
        if calls.count("sofascore") == 2:
            raise TimeoutError("shadow timeout")
        return {"ok": True}

    candidates = [
        Candidate(name="fotmob", fetch=fotmob_fetch),
        Candidate(name="sofascore", fetch=sofascore_fetch),
    ]
    result = execute_transport_plan(interleaved_request_plan(candidates, rounds=3))

    assert calls == ["fotmob", "sofascore"] * 3
    assert result["upstream_request_count"] == 6
    assert result["request_failures"] == 1
    assert [trace["sequence"] for trace in result["traces"]] == list(range(1, 7))
    assert [trace["source"] for trace in result["traces"]] == ["fotmob", "sofascore"] * 3
    assert sum(trace["success"] for trace in result["traces"]) == 5
