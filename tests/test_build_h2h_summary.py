import unittest

from scripts.build_h2h_summary import valid_sofascore_summary


class BuildH2HSummaryTests(unittest.TestCase):
    def test_verified_sofascore_h2h_can_override(self):
        row = {
            "mapping_status": "VERIFIED",
            "quality": "H2H_OK",
            "h2h_games": "2",
            "home_wins": "1",
            "draws": "1",
            "away_wins": "0",
            "home_goals": "4",
            "away_goals": "2",
            "avg_total_goals": "3.00",
            "last5": "HD",
            "meetings_json": '[{"source_event_id":1},{"source_event_id":2}]',
        }
        out = valid_sofascore_summary(row)
        self.assertIsNotNone(out)
        self.assertEqual(out["source"], "SOFASCORE verified direct H2H")
        self.assertEqual(out["h2h_games"], 2)

    def test_unmapped_sofascore_never_overrides(self):
        row = {
            "mapping_status": "UNMAPPED",
            "quality": "H2H_OK",
            "h2h_games": "2",
            "home_wins": "1",
            "draws": "1",
            "away_wins": "0",
            "home_goals": "4",
            "away_goals": "2",
            "meetings_json": '[{"source_event_id":1}]',
        }
        self.assertIsNone(valid_sofascore_summary(row))

    def test_no_history_never_erases_existing_hkjc_h2h(self):
        row = {
            "mapping_status": "VERIFIED",
            "quality": "NO_HISTORY",
            "h2h_games": "0",
            "home_wins": "0",
            "draws": "0",
            "away_wins": "0",
            "home_goals": "0",
            "away_goals": "0",
            "meetings_json": "[]",
        }
        self.assertIsNone(valid_sofascore_summary(row))

    def test_malformed_summary_fails_closed(self):
        row = {
            "mapping_status": "VERIFIED",
            "quality": "H2H_OK",
            "h2h_games": "2",
            "home_wins": "2",
            "draws": "1",
            "away_wins": "0",
            "home_goals": "4",
            "away_goals": "2",
            "meetings_json": "not-json",
        }
        self.assertIsNone(valid_sofascore_summary(row))


if __name__ == "__main__":
    unittest.main()
