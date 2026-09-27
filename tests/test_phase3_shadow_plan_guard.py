from phase3.source_latency_benchmark import Candidate
from phase3.source_shadow_runner import interleaved_request_plan


def test_plan_requires_two_sources():
    try:
        interleaved_request_plan([], rounds=3)
    except ValueError as exc:
        assert "at least two sources required" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_plan_is_bounded_and_interleaved_for_two_sources():
    candidates = [
        Candidate(name="fotmob", fetch=lambda: {}),
        Candidate(name="sofascore", fetch=lambda: {}),
    ]

    plan = interleaved_request_plan(candidates, rounds=3)

    assert len(plan) == 6
    assert [slot["sequence"] for slot in plan] == [1, 2, 3, 4, 5, 6]
    assert [slot["source"] for slot in plan] == [
        "fotmob",
        "sofascore",
        "fotmob",
        "sofascore",
        "fotmob",
        "sofascore",
    ]
    assert [slot["candidate"].name for slot in plan] == [
        "fotmob",
        "sofascore",
        "fotmob",
        "sofascore",
        "fotmob",
        "sofascore",
    ]
