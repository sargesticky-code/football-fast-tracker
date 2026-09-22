import unittest

from phase3.fast_lane import fast_lane_health, normalize_fotmob_board


class FastLaneSignedValueTests(unittest.TestCase):
    def test_negative_numeric_strings_fail_closed(self):
        now = "2026-09-22T09:00:10+00:00"
        for row in (
            {"status": "2nd", "minute": "67", "home_score": "-1", "away_score": "0"},
            {"status": "2nd", "minute": "67", "home_score": "1", "away_score": "-1"},
            {"status": "2nd", "minute": "-1", "home_score": "1", "away_score": "0"},
        ):
            health = fast_lane_health(
                [row], "2026-09-22T09:00:09+00:00", now=now
            )
            self.assertEqual(health["health"], "FRESH_PARTIAL_OR_TERMINAL")
            self.assertEqual(health["live_rows"], 0)

    def test_normalizer_preserves_negative_source_score_for_validation(self):
        payload = {
            "matches": [{
                "id": 15,
                "home": {"score": "-1"},
                "away": {"score": "0"},
                "status": {"liveTime": {"short": "67'"}, "reason": {"short": "2nd"}},
            }]
        }
        row = normalize_fotmob_board(payload, "2026-09-22T09:00:09+00:00")[0]
        self.assertEqual(row["home_score"], -1)
        health = fast_lane_health([row], row["observed_at"], now="2026-09-22T09:00:10+00:00")
        self.assertEqual(health["health"], "FRESH_PARTIAL_OR_TERMINAL")
        self.assertEqual(health["live_rows"], 0)


if __name__ == "__main__":
    unittest.main()
