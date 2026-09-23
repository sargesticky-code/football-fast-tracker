import unittest

from phase3.fast_lane import fast_lane_health, normalize_fotmob_board


class FastLaneScorePairTests(unittest.TestCase):
    def _row(self, score_str):
        payload = {
            "matches": [{
                "id": 11,
                "status": {
                    "liveTime": {"short": "67'"},
                    "reason": {"short": "2nd"},
                    "scoreStr": score_str,
                },
            }]
        }
        return normalize_fotmob_board(payload, "2026-09-23T00:00:00+00:00")[0]

    def test_normal_score_pair_still_parses(self):
        row = self._row("2 - 1")
        self.assertEqual((row["home_score"], row["away_score"]), (2, 1))

    def test_negative_home_score_is_preserved_and_fails_closed(self):
        row = self._row("-1 - 0")
        self.assertEqual((row["home_score"], row["away_score"]), (-1, 0))
        health = fast_lane_health([row], "2026-09-23T00:00:00+00:00", now="2026-09-23T00:00:01+00:00")
        self.assertEqual(health["health"], "FRESH_PARTIAL_OR_TERMINAL")
        self.assertEqual(health["live_rows"], 0)

    def test_negative_away_score_is_preserved_and_fails_closed(self):
        row = self._row("1 - -2")
        self.assertEqual((row["home_score"], row["away_score"]), (1, -2))
        health = fast_lane_health([row], "2026-09-23T00:00:00+00:00", now="2026-09-23T00:00:01+00:00")
        self.assertEqual(health["health"], "FRESH_PARTIAL_OR_TERMINAL")
        self.assertEqual(health["live_rows"], 0)

    def test_malformed_score_string_does_not_invent_pair(self):
        row = self._row("2 - 1 garbage")
        self.assertIsNone(row["home_score"])
        self.assertIsNone(row["away_score"])
        health = fast_lane_health([row], "2026-09-23T00:00:00+00:00", now="2026-09-23T00:00:01+00:00")
        self.assertEqual(health["health"], "FRESH_PARTIAL_OR_TERMINAL")
        self.assertEqual(health["live_rows"], 0)


if __name__ == "__main__":
    unittest.main()
