import unittest

from phase3.fast_lane import fast_lane_health, normalize_fotmob_board


class FractionalMinuteFailClosedTests(unittest.TestCase):
    def test_fractional_numeric_live_time_is_not_truncated_into_fake_elapsed_minute(self):
        payload = {
            "matches": [
                {
                    "id": 991,
                    "home": {"score": 1},
                    "away": {"score": 0},
                    "status": {"liveTime": 67.5, "reason": {"short": "2nd"}},
                }
            ]
        }
        row = normalize_fotmob_board(payload, "2026-09-23T09:45:00+00:00")[0]
        self.assertIsNone(row["minute"])
        health = fast_lane_health(
            [row],
            "2026-09-23T09:45:00+00:00",
            now="2026-09-23T09:45:01+00:00",
        )
        self.assertEqual(health["health"], "FRESH_PARTIAL_OR_TERMINAL")
        self.assertEqual(health["live_rows"], 0)

    def test_integral_numeric_live_time_remains_valid(self):
        payload = {
            "matches": [
                {
                    "id": 992,
                    "home": {"score": 1},
                    "away": {"score": 0},
                    "status": {"liveTime": 68.0, "reason": {"short": "2nd"}},
                }
            ]
        }
        row = normalize_fotmob_board(payload, "2026-09-23T09:45:00+00:00")[0]
        self.assertEqual(row["minute"], 68)
        health = fast_lane_health(
            [row],
            "2026-09-23T09:45:00+00:00",
            now="2026-09-23T09:45:01+00:00",
        )
        self.assertEqual(health["health"], "FRESH_LIVE")
        self.assertEqual(health["live_rows"], 1)


if __name__ == "__main__":
    unittest.main()
