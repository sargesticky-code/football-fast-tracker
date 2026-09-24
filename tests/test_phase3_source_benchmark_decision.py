import unittest

from phase3.source_benchmark_decision import assess_candidate


class SourceBenchmarkDecisionTests(unittest.TestCase):
    def test_candidate_must_be_consistently_faster_and_not_staler(self):
        benchmark = {"mode": "SHADOW_ONLY", "sources": {"fotmob": {"samples": 5, "failure_rate": 0.0, "identity_match_rate": 1.0, "median_latency_ms": 120.0, "p95_latency_ms": 180.0, "median_source_age_seconds": 4.0}, "candidate": {"samples": 5, "failure_rate": 0.0, "identity_match_rate": 1.0, "median_latency_ms": 80.0, "p95_latency_ms": 130.0, "median_source_age_seconds": 3.0}}}
        result = assess_candidate(benchmark, baseline="fotmob", candidate="candidate")
        self.assertTrue(result["promotion_ready"])
        self.assertFalse(result["production_primary_changed"])

    def test_stale_or_identity_unsafe_candidate_fails_closed(self):
        benchmark = {"mode": "SHADOW_ONLY", "sources": {"fotmob": {"samples": 5, "failure_rate": 0.0, "identity_match_rate": 1.0, "median_latency_ms": 120.0, "p95_latency_ms": 180.0, "median_source_age_seconds": 4.0}, "candidate": {"samples": 5, "failure_rate": 0.2, "identity_match_rate": 0.8, "median_latency_ms": 70.0, "p95_latency_ms": 100.0, "median_source_age_seconds": 9.0}}}
        result = assess_candidate(benchmark, baseline="fotmob", candidate="candidate")
        self.assertFalse(result["promotion_ready"])
        self.assertIn("candidate:FAILURE_RATE", result["blockers"])
        self.assertIn("candidate:IDENTITY_COVERAGE", result["blockers"])

    def test_p95_must_also_improve(self):
        benchmark = {"mode": "SHADOW_ONLY", "sources": {"fotmob": {"samples": 5, "failure_rate": 0.0, "identity_match_rate": 1.0, "median_latency_ms": 120.0, "p95_latency_ms": 180.0, "median_source_age_seconds": 4.0}, "candidate": {"samples": 5, "failure_rate": 0.0, "identity_match_rate": 1.0, "median_latency_ms": 70.0, "p95_latency_ms": 220.0, "median_source_age_seconds": 3.0}}}
        result = assess_candidate(benchmark, baseline="fotmob", candidate="candidate")
        self.assertIn("CANDIDATE_NOT_CONSISTENTLY_FASTER", result["blockers"])


if __name__ == "__main__":
    unittest.main()
