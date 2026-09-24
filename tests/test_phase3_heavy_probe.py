import unittest

from phase3.heavy_probe import _exit_evidence, run_probe


class _FakeService:
    def collect(self, fast_state, *, now=None):
        return {
            "fast_observed_at": fast_state.get("observed_at"),
            "heavy_observed_at": "2026-09-24T12:00:01Z",
            "eligible_rows": 2,
            "rejected_rows": 1,
            "heavy_usable_rows": 1,
            "detail_empty_rows": 0,
            "source_gap_rows": 0,
            "deferred_rows": 1,
            "requests_used": 1,
            "request_budget": 1,
            "source_requests": {"attempted": 1, "succeeded": 1, "failed": 0},
            "request_count_consistent": True,
            "min_interval_seconds": 45.0,
            "heavy_field_coverage": {"xg": 1, "shots": 1, "corners": 1},
            "heavy_fields_observed": 3,
            "request_failures": [],
            "deferred_event_ids": ["FB2"],
            "rejected_event_ids": ["FB3"],
            "heavy_rows": [{
                "hkjc_event_id": "FB1",
                "external_source": "fotmob",
                "external_id": "101",
                "heavy_status": "USABLE",
                "heavy_observed_at": "2026-09-24T12:00:01Z",
                "heavy_usable_fields": ["xg", "shots", "corners"],
                "heavy_usable_field_count": 3,
                "xg": {"home": 1.2, "away": 0.6},
            }],
        }


class HeavyProbeTests(unittest.TestCase):
    def test_probe_emits_compact_request_and_coverage_evidence(self):
        evidence = run_probe(
            {"observed_at": "2026-09-24T12:00:00Z", "rows": []},
            service=_FakeService(),
        )
        self.assertEqual(6, evidence["layer"])
        self.assertTrue(evidence["exit_evidence_ready"])
        self.assertIsNone(evidence["exit_evidence_blocker"])
        self.assertEqual(2, evidence["eligible_rows"])
        self.assertEqual(1, evidence["heavy_usable_rows"])
        self.assertEqual(1, evidence["deferred_rows"])
        self.assertEqual(1, evidence["source_requests"]["attempted"])
        self.assertTrue(evidence["request_count_consistent"])
        self.assertEqual(3, evidence["heavy_fields_observed"])
        self.assertEqual(["xg", "shots", "corners"], evidence["observations"][0]["heavy_usable_fields"])
        self.assertNotIn("xg", evidence["observations"][0])

    def test_probe_preserves_zero_request_fail_closed_evidence(self):
        class ZeroService:
            def collect(self, fast_state, *, now=None):
                return {
                    "eligible_rows": 0, "rejected_rows": 2,
                    "heavy_usable_rows": 0, "detail_empty_rows": 0,
                    "source_gap_rows": 0, "deferred_rows": 0,
                    "requests_used": 0, "request_budget": 2,
                    "source_requests": {"attempted": 0, "succeeded": 0, "failed": 0},
                    "request_count_consistent": True, "min_interval_seconds": 45.0,
                    "heavy_field_coverage": {}, "heavy_fields_observed": 0,
                    "request_failures": [], "deferred_event_ids": [],
                    "rejected_event_ids": ["FBX", "FBY"], "heavy_rows": [],
                }
        evidence = run_probe({"rows": []}, service=ZeroService())
        self.assertFalse(evidence["exit_evidence_ready"])
        self.assertEqual("NO_HKJC_VERIFIED_LIVE_TARGET", evidence["exit_evidence_blocker"])
        self.assertEqual(0, evidence["source_requests"]["attempted"])
        self.assertEqual([], evidence["observations"])
        self.assertTrue(evidence["request_count_consistent"])

    def test_exit_evidence_reports_request_and_source_blockers(self):
        base = {
            "eligible_rows": 1,
            "heavy_usable_rows": 0,
            "detail_empty_rows": 0,
            "source_gap_rows": 0,
            "deferred_rows": 0,
            "source_requests": {"attempted": 1},
            "request_count_consistent": True,
        }
        ready, blocker = _exit_evidence({**base, "request_count_consistent": False})
        self.assertFalse(ready)
        self.assertEqual("REQUEST_COUNT_MISMATCH", blocker)
        ready, blocker = _exit_evidence({**base, "detail_empty_rows": 1})
        self.assertFalse(ready)
        self.assertEqual("DETAIL_EMPTY", blocker)
        ready, blocker = _exit_evidence({**base, "source_gap_rows": 1})
        self.assertFalse(ready)
        self.assertEqual("SOURCE_GAP", blocker)


if __name__ == "__main__":
    unittest.main()
