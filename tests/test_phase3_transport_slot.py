from phase3.source_latency_benchmark import Candidate
from phase3.source_shadow_runner import execute_transport_slot


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
