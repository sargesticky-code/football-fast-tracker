import unittest

from phase3.fast_lane import fast_lane_health, join_verified_fast_rows, normalize_fotmob_board


class StrictNumericFastLaneTests(unittest.TestCase):
    def test_fractional_team_score_string_cannot_be_truncated_into_live_score(self):
        payload = {"matches": [{
            "id": 21,
            "home": {"score": "1.5"},
            "away": {"score": "0"},
            "status": {"liveTime": {"short": "23'"}, "reason": {"short": "1st"}},
        }]}
        row = normalize_fotmob_board(payload, "2026-09-23T10:00:00+00:00")[0]
        self.assertIsNone(row["home_score"])
        self.assertEqual(row["away_score"], 0)
        health = fast_lane_health([row], "2026-09-23T10:00:00+00:00", now="2026-09-23T10:00:01+00:00")
        self.assertEqual(health["health"], "FRESH_PARTIAL_OR_TERMINAL")
        self.assertEqual(health["live_rows"], 0)

    def test_decorated_score_string_cannot_be_partially_parsed(self):
        registry = [{"hkjc_event_id": "FB1", "source": "FOTMOB", "external_id": "21", "status": "VERIFIED"}]
        board = [{
            "source": "FOTMOB", "external_id": "21", "status": "1st", "minute": 23,
            "home_score": "1 goal", "away_score": "0", "observed_at": "2026-09-23T10:00:00+00:00",
        }]
        joined, unmapped = join_verified_fast_rows(registry, board)
        self.assertEqual(unmapped, [])
        self.assertIsNone(joined[0]["home_score"])
        health = fast_lane_health(joined, "2026-09-23T10:00:00+00:00", now="2026-09-23T10:00:01+00:00")
        self.assertEqual(health["health"], "FRESH_PARTIAL_OR_TERMINAL")
        self.assertEqual(health["live_rows"], 0)

    def test_integer_float_score_is_accepted_without_truncation(self):
        payload = {"matches": [{
            "id": 22,
            "home": {"score": 2.0},
            "away": {"score": 1.0},
            "status": {"liveTime": {"short": "68'"}, "reason": {"short": "2nd"}},
        }]}
        row = normalize_fotmob_board(payload, "2026-09-23T10:00:00+00:00")[0]
        self.assertEqual((row["home_score"], row["away_score"]), (2, 1))
        health = fast_lane_health([row], "2026-09-23T10:00:00+00:00", now="2026-09-23T10:00:01+00:00")
        self.assertEqual(health["health"], "FRESH_LIVE")
        self.assertEqual(health["live_rows"], 1)


if __name__ == "__main__":
    unittest.main()
