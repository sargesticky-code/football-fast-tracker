from phase3.source_latency_benchmark import Candidate


def interleaved_request_order(candidates, rounds=3):
    if rounds < 1:
        raise ValueError("rounds must be >= 1")
    names = [candidate.name for candidate in candidates]
    if len(names) < 2:
        raise ValueError("at least two sources required")
    return names * rounds
