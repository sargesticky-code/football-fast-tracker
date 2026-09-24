import unittest

from phase3.heavy_collector import HeavyCollector, heavy_targets_from_fast_state
from phase3.heavy_lane import HeavyLane


class HeavyCollectorTests(unittest.TestCase):
    def test_targets_only_live_authorised_verified_rows(self):
        state = {"rows": [
            {"hkjc_event_id": "FB1", "external_source": "fotmob", "external_id": "101", "identity_status": "VERIFIED", "hkjc_authorised": True, "status": "LIVE", "minute": 51},
            {"hkjc_event_id": "FB2", "external_source": "fotmob", "external_id": "102", "identity_status": "UNRESOLVED", "hkjc_authorised": True, "status": "LIVE", "minute": 22},
            {"hkjc_event_id": "FB3", "external_source": "fotmob", "external_id": "103", "identity_status": "VERIFIED", "hkjc_authorised": False, "status": "LIVE", "minute": 33},
            {"hkjc_event_id": "FB4", "external_source": "fotmob", "external_id": "104", "identity_status": "VERIFIED", "hkjc_authorised": True, "status": "FT", "minute": 90},
        ]}
        targets, meta = heavy_targets_from_fast_state(state)
        self.assertEqual([t.hkjc_event_id for t in targets], ["FB1"])
        self.assertEqual(meta["heavy_target_rows"], 1)
        self.assertEqual(meta["heavy_target_rejected_rows"], 2)
        self.assertEqual({r["reason"] for r in meta["heavy_target_rejections"]}, {"IDENTITY_NOT_VERIFIED", "HKJC_NOT_AUTHORISED"})

    def test_duplicate_external_identity_fails_closed(self):
        state = {"rows": [
            {"hkjc_event_id": "FB1", "external_source": "fotmob", "external_id": "101", "identity_status": "VERIFIED", "hkjc_authorised": True, "status": "LIVE"},
            {"hkjc_event_id": "FB2", "external_source": "fotmob", "external_id": "101", "identity_status": "VERIFIED", "hkjc_authorised": True, "status": "LIVE"},
        ]}
        targets, meta = heavy_targets_from_fast_state(state)
        self.assertEqual(len(targets), 1)
        self.assertEqual(meta["heavy_target_rejections"][0]["reason"], "DUPLICATE_EXTERNAL_ID")

    def test_executable_collector_preserves_fast_and_heavy_timestamps_and_budget(self):
        calls = []
        def fetch(target):
            calls.append(target.external_id)
            return {"shots": {"home": 9, "away": 4}}
        lane = HeavyLane(fetch, min_interval_seconds=45, max_requests_per_cycle=1)
        collector = HeavyCollector(lane)
        state = {"observed_at": "2026-09-24T06:00:00Z", "rows": [
            {"hkjc_event_id": "FB1", "external_source": "fotmob", "external_id": "101", "identity_status": "VERIFIED", "hkjc_authorised": True, "status": "LIVE"},
            {"hkjc_event_id": "FB2", "external_source": "fotmob", "external_id": "102", "identity_status": "VERIFIED", "hkjc_authorised": True, "status": "2H"},
        ]}
        result = collector.collect(state, now="2026-09-24T06:00:10Z")
        self.assertEqual(calls, ["101"])
        self.assertEqual(result["requests_used"], 1)
        self.assertEqual(result["request_budget"], 1)
        self.assertEqual(result["heavy_usable_rows"], 1)
        self.assertEqual(result["deferred_rows"], 1)
        self.assertEqual(result["fast_observed_at"], "2026-09-24T06:00:00Z")
        self.assertEqual(result["heavy_observed_at"], "2026-09-24T06:00:10Z")

    def test_terminal_rows_never_trigger_heavy_fetch(self):
        calls = []
        lane = HeavyLane(lambda target: calls.append(target.external_id) or {}, min_interval_seconds=45)
        result = HeavyCollector(lane).collect({"rows": [
            {"hkjc_event_id": "FB1", "external_source": "fotmob", "external_id": "101", "identity_status": "VERIFIED", "hkjc_authorised": True, "status": "FINISHED", "minute": 90},
        ]}, now="2026-09-24T06:00:00Z")
        self.assertEqual(calls, [])
        self.assertEqual(result["requests_used"], 0)


if __name__ == "__main__":
    unittest.main()
