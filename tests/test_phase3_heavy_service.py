import json
import unittest

from phase3.fotmob_heavy_source import FotMobHeavySource
from phase3.heavy_service import HeavyService


class _Response:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.raw


def _payload():
    return {
        "content": {
            "stats": {
                "Periods": {
                    "All": {
                        "stats": [
                            {"title": "Expected goals (xG)", "stats": [1.25, 0.61]},
                            {"title": "Total shots", "stats": [12, 7]},
                            {"title": "Shots on target", "stats": [5, 2]},
                            {"title": "Ball possession", "stats": [58, 42]},
                            {"title": "Corners", "stats": [6, 3]},
                        ]
                    }
                }
            },
            "momentum": {"main": {"data": [{"minute": 52, "value": 18}]}}
        }
    }


def _row(event_id, external_id, status="LIVE"):
    return {
        "hkjc_event_id": event_id,
        "external_source": "fotmob",
        "external_id": external_id,
        "identity_status": "VERIFIED",
        "hkjc_authorised": True,
        "status": status,
        "minute": 52,
    }


class HeavyServiceTests(unittest.TestCase):
    def test_end_to_end_cycle_is_budgeted_and_exposes_actual_request_count(self):
        calls = []
        def opener(request, timeout=None):
            calls.append(request.full_url)
            return _Response(_payload())

        source = FotMobHeavySource(opener=opener)
        service = HeavyService(source=source, min_interval_seconds=45, max_requests_per_cycle=1)
        state = {"observed_at": "2026-09-24T08:00:00Z", "rows": [_row("FB1", "101"), _row("FB2", "102")]}
        result = service.collect(state, now="2026-09-24T08:00:01Z")

        self.assertEqual(1, len(calls))
        self.assertEqual(1, result["requests_used"])
        self.assertEqual(1, result["source_requests"]["attempted"])
        self.assertEqual(1, result["source_requests"]["succeeded"])
        self.assertTrue(result["request_count_consistent"])
        self.assertEqual(1, result["heavy_usable_rows"])
        self.assertEqual(1, result["deferred_rows"])
        self.assertEqual("2026-09-24T08:00:00Z", result["fast_observed_at"])
        self.assertEqual("2026-09-24T08:00:01Z", result["heavy_observed_at"])
        self.assertEqual({"home": 1.25, "away": 0.61}, result["heavy_rows"][0]["xg"])

    def test_non_verified_or_non_live_rows_make_zero_source_requests(self):
        calls = []
        source = FotMobHeavySource(opener=lambda *args, **kwargs: calls.append(args))
        service = HeavyService(source=source)
        bad = _row("FB1", "101")
        bad["identity_status"] = "UNRESOLVED"
        finished = _row("FB2", "102", status="FINISHED")
        result = service.collect({"rows": [bad, finished]}, now="2026-09-24T08:00:01Z")
        self.assertEqual([], calls)
        self.assertEqual(0, result["source_requests"]["attempted"])
        self.assertEqual(0, result["heavy_usable_rows"])
        self.assertTrue(result["request_count_consistent"])

    def test_cadence_guard_prevents_second_http_request_inside_45_seconds(self):
        calls = []
        def opener(request, timeout=None):
            calls.append(request.full_url)
            return _Response(_payload())
        source = FotMobHeavySource(opener=opener)
        service = HeavyService(source=source, min_interval_seconds=45, max_requests_per_cycle=1)
        state = {"rows": [_row("FB1", "101")]}
        first = service.collect(state, now="2026-09-24T08:00:00Z")
        second = service.collect(state, now="2026-09-24T08:00:20Z")
        self.assertEqual(1, len(calls))
        self.assertEqual(1, first["source_requests"]["attempted"])
        self.assertEqual(0, second["source_requests"]["attempted"])
        self.assertEqual(1, second["deferred_rows"])
        self.assertTrue(second["request_count_consistent"])


if __name__ == "__main__":
    unittest.main()
