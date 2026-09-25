from phase3.source_latency_benchmark import Candidate
from phase3.source_shadow_runner import interleaved_request_order


def test_interleaved_order_is_round_robin_and_bounded():
    noop = lambda: {}
    candidates = [Candidate("fotmob", noop), Candidate("sofascore", noop)]
    order = interleaved_request_order(candidates, rounds=3)
    assert order == ["fotmob", "sofascore", "fotmob", "sofascore", "fotmob", "sofascore"]
    assert len(order) == 6


def test_interleaved_order_requires_two_sources():
    noop = lambda: {}
    try:
        interleaved_request_order([Candidate("fotmob", noop)], rounds=3)
    except ValueError as exc:
        assert "two sources" in str(exc)
    else:
        raise AssertionError("expected fail-closed ValueError")
