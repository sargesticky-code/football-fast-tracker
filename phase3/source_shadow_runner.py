from phase3.source_latency_benchmark import Candidate


def interleaved_request_order(candidates, rounds=3):
    if rounds < 1:
        raise ValueError("rounds must be >= 1")
    names = [candidate.name for candidate in candidates]
    if len(names) < 2:
        raise ValueError("at least two sources required")
    return names * rounds


def interleaved_request_plan(candidates, rounds=3):
    """Return bounded sequential source slots for a same-window shadow run."""
    candidates = list(candidates)
    order = interleaved_request_order(candidates, rounds=rounds)
    by_name = {candidate.name: candidate for candidate in candidates}
    return [
        {"sequence": sequence, "source": name, "candidate": by_name[name]}
        for sequence, name in enumerate(order, start=1)
    ]
