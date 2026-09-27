from phase3.source_shadow_runner import interleaved_request_plan


def test_plan_requires_two_sources():
    try:
        interleaved_request_plan([], rounds=3)
    except ValueError as exc:
        assert "at least two sources required" in str(exc)
    else:
        raise AssertionError("expected ValueError")
