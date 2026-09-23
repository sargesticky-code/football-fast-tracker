import unittest

from phase3.fast_consumer import project_fast_state


class FastConsumerTests(unittest.TestCase):
    def base(self, **overrides):
        state = {
            "health": "FRESH_LIVE", "observed_at": "2026-09-24T00:00:00+00:00",
            "snapshot_age_seconds": 2.0, "request_failures": 0,
            "mapped_rows": 1, "live_rows": 1, "unmapped_count": 0,
            "rows": [{"hkjc_event_id": "FB1", "status": "2ND", "minute": 61,
                      "home_score": 1, "away_score": 0}],
            "shared_cache": {"status": "HIT", "lease_age_seconds": 2.0, "upstream_refreshes": 1},
        }
        state.update(overrides)
        return state

    def test_fresh_live_projects_as_fresh(self):
        view = project_fast_state(self.base())
        self.assertEqual("FRESH", view["display_state"])
        self.assertEqual("MAPPED", view["identity_state"])
        self.assertEqual(61, view["matches"][0]["minute"])

    def test_stale_is_explicit(self):
        view = project_fast_state(self.base(health="STALE_FAST_SNAPSHOT", snapshot_age_seconds=20.0))
        self.assertEqual("STALE", view["display_state"])

    def test_request_failure_takes_precedence(self):
        view = project_fast_state(self.base(health="REQUEST_FAILED", request_failures=1, unmapped_count=1))
        self.assertEqual("REQUEST_FAILED", view["display_state"])

    def test_unmapped_is_fail_closed(self):
        view = project_fast_state(self.base(unmapped_count=1, unmapped_external_ids=["99"], live_rows=0))
        self.assertEqual("UNMAPPED", view["display_state"])
        self.assertEqual("UNMAPPED", view["identity_state"])

    def test_collision_is_identity_gap(self):
        view = project_fast_state(self.base(collision_count=1, live_rows=0))
        self.assertEqual("IDENTITY_GAP", view["display_state"])
        self.assertEqual("IDENTITY_GAP", view["identity_state"])

    def test_consumer_cannot_mutate_shared_rows(self):
        state = self.base()
        view = project_fast_state(state)
        view["matches"][0]["minute"] = 99
        self.assertEqual(61, state["rows"][0]["minute"])


if __name__ == "__main__":
    unittest.main()
