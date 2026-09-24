import unittest

from phase3.heavy_lane import HEAVY_FIELDS, HeavyLane, HeavyTarget


class HeavyLaneTests(unittest.TestCase):
    def target(self, event="FB1", external="101", **kw):
        return HeavyTarget(event, "fotmob", external, **kw)

    def test_rejects_unverified_and_non_hkjc_targets_without_fetch(self):
        calls = []
        lane = HeavyLane(lambda target: calls.append(target) or {"xg": [1.1, .7]})
        result = lane.collect([
            self.target(),
            self.target("FB2", "102", identity_status="UNRESOLVED"),
            self.target("FB3", "103", hkjc_authorised=False),
        ], now="2026-09-24T03:00:00Z")
        self.assertEqual(1, result["requests_used"])
        self.assertEqual(2, result["rejected_rows"])
        self.assertEqual(["FB2", "FB3"], result["rejected_event_ids"])
        self.assertEqual(1, len(calls))

    def test_enforces_45_second_guard_independent_of_fast_lane(self):
        calls = []
        lane = HeavyLane(lambda target: calls.append(target.external_id) or {"shots": [5, 4]})
        target = self.target()
        first = lane.collect([target], now="2026-09-24T03:00:00Z")
        guarded = lane.collect([target], now="2026-09-24T03:00:05Z")
        ready = lane.collect([target], now="2026-09-24T03:00:46Z")
        self.assertEqual((1, 0, 1), (first["requests_used"], guarded["requests_used"], ready["requests_used"]))
        self.assertEqual(1, guarded["deferred_rows"])
        self.assertEqual(["101", "101"], calls)

    def test_request_budget_rotates_targets(self):
        calls = []
        lane = HeavyLane(lambda target: calls.append(target.hkjc_event_id) or {"corners": [2, 3]}, max_requests_per_cycle=2)
        targets = [self.target(f"FB{i}", str(100 + i)) for i in range(1, 5)]
        one = lane.collect(targets, now="2026-09-24T03:00:00Z")
        two = lane.collect(targets, now="2026-09-24T03:01:00Z")
        self.assertEqual(2, one["requests_used"])
        self.assertEqual(2, one["deferred_rows"])
        self.assertEqual(["FB1", "FB2", "FB3", "FB4"], calls)
        self.assertEqual(2, two["requests_used"])

    def test_exposes_all_heavy_fields_and_separate_timestamp(self):
        lane = HeavyLane(lambda target: {"xg": [1.2, .8], "momentum": [1, -1]})
        result = lane.collect([self.target()], now="2026-09-24T03:00:00Z")
        row = result["heavy_rows"][0]
        self.assertEqual("USABLE", row["heavy_status"])
        self.assertEqual("2026-09-24T03:00:00Z", row["heavy_observed_at"])
        self.assertNotIn("observed_at", row)
        for field in HEAVY_FIELDS:
            self.assertIn(field, row)

    def test_empty_and_source_gap_diagnostics(self):
        def fetch(target):
            if target.hkjc_event_id == "FB2":
                raise TimeoutError("source gap")
            return {}
        lane = HeavyLane(fetch, max_requests_per_cycle=2)
        result = lane.collect([self.target(), self.target("FB2", "102")], now="2026-09-24T03:00:00Z")
        self.assertEqual(1, result["detail_empty_rows"])
        self.assertEqual(1, result["source_gap_rows"])
        self.assertEqual(2, result["requests_used"])
        self.assertEqual("TimeoutError", result["request_failures"][0]["error"])

    def test_refuses_sub_30_second_heavy_cadence(self):
        with self.assertRaises(ValueError):
            HeavyLane(lambda target: {}, min_interval_seconds=5)


if __name__ == "__main__":
    unittest.main()
