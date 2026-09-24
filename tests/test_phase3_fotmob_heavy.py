import unittest
from phase3.fotmob_heavy import normalize_fotmob_heavy, make_fotmob_detail_fetcher
from phase3.heavy_lane import HeavyLane, HeavyTarget


class FotMobHeavyTests(unittest.TestCase):
    def test_normalizes_heavy_pairs_and_events(self):
        payload = {
            "stats": {
                "Expected goals (xG)": {"home": "1.42", "away": "0.71"},
                "Total shots": [13, 7],
                "Shots on target": {"homeValue": 5, "awayValue": 2},
                "Ball possession": ["61%", "39%"],
                "Touches in opposition box": [24, 11],
                "Big chances": [3, 1],
                "Corners": [6, 2],
            },
            "events": [{"type": "Goal", "minute": 52}],
            "momentum": [{"minute": 52, "value": 0.8}],
        }
        row = normalize_fotmob_heavy(payload)
        self.assertEqual(row["xg"], {"home": 1.42, "away": 0.71})
        self.assertEqual(row["shots"], {"home": 13, "away": 7})
        self.assertEqual(row["shots_on_target"], {"home": 5, "away": 2})
        self.assertEqual(row["possession"], {"home": 61, "away": 39})
        self.assertEqual(row["box_touches"], {"home": 24, "away": 11})
        self.assertEqual(row["big_chances"], {"home": 3, "away": 1})
        self.assertEqual(row["corners"], {"home": 6, "away": 2})
        self.assertEqual(len(row["events"]), 1)
        self.assertEqual(len(row["momentum"]), 1)

    def test_missing_detail_is_not_fabricated(self):
        row = normalize_fotmob_heavy({"stats": {}})
        self.assertTrue(all(value is None for value in row.values()))

    def test_adapter_and_heavy_lane_use_one_request_per_target(self):
        calls = []
        def fetch_json(match_id):
            calls.append(match_id)
            return {"stats": {"Total shots": [8, 4], "Corners": [3, 1]}}
        lane = HeavyLane(make_fotmob_detail_fetcher(fetch_json), min_interval_seconds=45, max_requests_per_cycle=1)
        result = lane.collect([
            HeavyTarget("FB1", "fotmob", "1001"),
            HeavyTarget("FB2", "fotmob", "1002"),
        ], now="2026-09-24T04:50:00Z")
        self.assertEqual(calls, ["1001"])
        self.assertEqual(result["requests_used"], 1)
        self.assertEqual(result["heavy_usable_rows"], 1)
        self.assertEqual(result["deferred_rows"], 1)
        self.assertEqual(result["heavy_rows"][0]["shots"], {"home": 8, "away": 4})

    def test_non_fotmob_source_fails_closed(self):
        fetcher = make_fotmob_detail_fetcher(lambda match_id: {})
        with self.assertRaises(ValueError):
            fetcher(HeavyTarget("FB1", "espn", "1"))


if __name__ == "__main__":
    unittest.main()
