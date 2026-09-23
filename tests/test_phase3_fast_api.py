import unittest

from phase3.fast_api import fast_api_response


class Reader:
    def __init__(self, state=None, error=None):
        self.state = state or {}
        self.error = error
        self.calls = 0

    def read(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.state


class FastApiTests(unittest.TestCase):
    def test_fresh_payload_reads_shared_service_once(self):
        reader = Reader({
            "health": "FRESH_LIVE", "observed_at": "2026-09-24T00:00:00Z",
            "snapshot_age_seconds": 1.2, "request_failures": 0,
            "mapped_rows": 1, "live_rows": 1, "unmapped_count": 0,
            "rows": [{"hkjc_match_id": "FB1", "score": "1-0", "minute": 34, "status": "LIVE"}],
            "shared_cache": {"status": "HIT", "lease_age_seconds": 1.2, "upstream_refreshes": 1},
        })
        status, headers, body = fast_api_response(reader)
        self.assertEqual(200, status)
        self.assertEqual(1, reader.calls)
        self.assertEqual("FRESH", body["display_state"])
        self.assertEqual("1-0", body["matches"][0]["score"])
        self.assertEqual("no-store", headers["Cache-Control"])
        self.assertEqual(1, body["shared_cache"]["upstream_refreshes"])

    def test_unmapped_is_valid_fail_closed_response(self):
        reader = Reader({"health": "FRESH_NO_LIVE_ROWS", "mapped_rows": 0,
                         "unmapped_count": 1, "unmapped_external_ids": ["99"],
                         "missing_target_ids": ["99"], "rows": []})
        status, _, body = fast_api_response(reader)
        self.assertEqual(200, status)
        self.assertEqual("UNMAPPED", body["display_state"])
        self.assertEqual([], body["matches"])

    def test_identity_collision_is_valid_fail_closed_response(self):
        reader = Reader({"health": "FRESH_NO_LIVE_ROWS", "collision_count": 1, "rows": []})
        status, _, body = fast_api_response(reader)
        self.assertEqual(200, status)
        self.assertEqual("IDENTITY_GAP", body["display_state"])

    def test_stale_and_request_failed_render_without_fallback_fetch(self):
        stale = Reader({"health": "STALE_FAST_SNAPSHOT", "snapshot_age_seconds": 9, "rows": []})
        failed = Reader({"health": "REQUEST_FAILED", "request_failures": 1, "rows": []})
        self.assertEqual("STALE", fast_api_response(stale)[2]["display_state"])
        self.assertEqual("REQUEST_FAILED", fast_api_response(failed)[2]["display_state"])
        self.assertEqual(1, stale.calls)
        self.assertEqual(1, failed.calls)

    def test_service_failure_returns_503_and_never_fabricates_matches(self):
        reader = Reader(error=RuntimeError("refresh failed"))
        status, _, body = fast_api_response(reader)
        self.assertEqual(503, status)
        self.assertEqual("SERVICE_UNAVAILABLE", body["health"])
        self.assertEqual([], body["matches"])
        self.assertEqual(1, reader.calls)


if __name__ == "__main__":
    unittest.main()
