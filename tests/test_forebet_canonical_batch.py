import unittest
from datetime import datetime, timezone, timedelta
from scripts.forebet_canonical_batch import validated_rows

NOW = datetime(2026, 10, 9, 11, 0, tzinfo=timezone.utc)
SAMPLE = {
    "hkjc_event_id": "FB6342",
    "hkjc_home_team": "Arsenal",
    "hkjc_away_team": "Leeds",
    "hkjc_kickoff_hkt": "2026-10-10 19:30",
    "home_team": "Arsenal",
    "away_team": "Leeds",
    "fetched_at_hkt": "2026-10-09 18:30:00",
    "prob_home": "48", "prob_draw": "27", "prob_away": "25",
    "prediction_1x2": "1", "predicted_score": "2 - 1", "avg_goals": "2.83", "match_score": "0.995",
}
STATE = [{"hkjc_event_id": "FB6342", "state": "MODEL"}]


class ForebetBatchTests(unittest.TestCase):
    def test_valid_model_preserves_source_capture_and_exact_fixture(self):
        result = validated_rows([dict(SAMPLE)], STATE, NOW)
        self.assertEqual(result[0]["match_id"], "FB6342")
        self.assertEqual(result[0]["captured_at"], "2026-10-09T10:30:00+00:00")
        self.assertEqual(result[0]["kickoff"], "2026-10-10T11:30:00+00:00")
        self.assertEqual([result[0][k] for k in ("home", "draw", "away")], [48, 27, 25])
        self.assertEqual(result[0]["score"], "2 - 1")
        self.assertEqual(result[0]["avg_goals"], 2.83)

    def test_genuine_absence_makes_no_rows(self):
        self.assertEqual(validated_rows([], STATE, NOW), [])

    def test_unresolved_cannot_publish(self):
        with self.assertRaisesRegex(ValueError, "availability"):
            validated_rows([dict(SAMPLE)], [{"hkjc_event_id":"FB6342","state":"UNRESOLVED"}], NOW)

    def test_challenge_or_empty_prediction_rejected(self):
        row = dict(SAMPLE, prob_home="")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            validated_rows([row], STATE, NOW)

    def test_stale_snapshot_rejected(self):
        row = dict(SAMPLE, fetched_at_hkt="2026-09-28 15:30:17")
        with self.assertRaisesRegex(ValueError, "stale"):
            validated_rows([row], STATE, NOW)

    def test_future_snapshot_rejected(self):
        row = dict(SAMPLE, fetched_at_hkt="2026-10-10 22:30:17")
        with self.assertRaisesRegex(ValueError, "future"):
            validated_rows([row], STATE, NOW)

    def test_duplicate_fixture_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validated_rows([dict(SAMPLE),dict(SAMPLE)], STATE, NOW)

    def test_invalid_probability_rejected(self):
        for changes in [{"prob_home":"-2"},{"prob_home":"200"},{"prob_away":"0"}]:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    validated_rows([dict(SAMPLE, **changes)], STATE, NOW)

    def test_missing_forebet_average_goals_is_not_faked(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            validated_rows([dict(SAMPLE, avg_goals="")], STATE, NOW)

    def test_invalid_forebet_average_goals_rejected(self):
        for invalid in ("nan", "-1", "999"):
            with self.subTest(value=invalid):
                with self.assertRaisesRegex(ValueError, "average goals"):
                    validated_rows([dict(SAMPLE, avg_goals=invalid)], STATE, NOW)

    def test_unverified_identity_rejected(self):
        with self.assertRaisesRegex(ValueError, "confidence"):
            validated_rows([dict(SAMPLE, match_score="0.6")], STATE, NOW)

    def test_malformed_score_rejected(self):
        with self.assertRaisesRegex(ValueError, "prediction"):
            validated_rows([dict(SAMPLE, predicted_score="Just a moment...")], STATE, NOW)


if __name__ == "__main__":
    unittest.main()
