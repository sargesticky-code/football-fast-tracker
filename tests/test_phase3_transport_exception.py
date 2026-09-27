from phase3.source_latency_benchmark import Candidate
from phase3.source_shadow_runner import execute_transport_slot

def test_transport_slot_isolates_exception_once():
    calls = []
    def fail():
        calls.append(1)
        raise RuntimeError("upstream unavailable")
    candidate = Candidate(name="sofascore", fetch=fail)
    trace = execute_transport_slot({"sequence": 2, "source": "sofascore", "candidate": candidate})
    assert calls == [1]
    assert trace["success"] is False
    assert trace["payload"] is None
    assert trace["error"] == "RuntimeError: upstream unavailable"
