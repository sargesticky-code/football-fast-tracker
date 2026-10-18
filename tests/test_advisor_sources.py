#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from capture_advisor_sources import (
    betclan_detail, sportytrader_detail, extract_links, capture,
)

BETCLAN_URL = "https://www.betclan.com/predictionsdetails/football/201865300/nacional-v-torque-prediction-h2h-tip-and-match-preview/"
SPORTY_URL = "https://www.sportytrader.com/en/betting-tips/norwich-southampton-378798/"


class AdvisorCaptureTests(unittest.TestCase):
    def test_betclan_primary_markets_and_user_votes_separation(self):
        html = """<h1>Nacional De Football vs Montevideo City Torque Prediction, H2H, Tip and Match Preview</h1>
        <div>Date 2026-10-06 00:00</div><h4>Winner</h4><h5>Nacional De Football</h5>
        Home 48% Draw 23% Away 29%
        <h4>Total Goals 2.5</h4><h5>Over 2.5</h5>Under 46% Over 54%
        <h4>Both Teams to Score BTTS</h4><h5>Yes</h5>Yes 57% No 43%
        <h4>Correct Score</h4><h5>2-1</h5>2-1 19% Others 81%
        <h2>Team Momentum Performance Ranking</h2>
        <h2>Users Average</h2> Home 90% Draw 5% Away 5%"""
        row = betclan_detail(html, BETCLAN_URL)
        self.assertEqual(row["provider_event_id"], "201865300")
        self.assertEqual(row["prediction_1x2"], {"home": 48, "draw": 23, "away": 29})
        self.assertEqual(row["goals_25"], {"under": 46, "over": 54})
        self.assertEqual(row["btts"], {"yes": 57, "no": 43})
        self.assertEqual(row["correct_score"], {"score": "2-1", "probability": 19})
        self.assertIsNone(row["canonical_match_id"])
        self.assertFalse(row["source_timezone_verified"])

    def test_sporty_model_only_not_form_or_bookmaker(self):
        html = """<h1>Norwich vs Southampton Prediction &amp; Betting Tips - Championship</h1>
        <section>Norwich 15/10/2026 00:15 Southampton Prediction : Southampton wins</section>
        <h2>What is the prediction for the football match between Norwich and Southampton?</h2>
        Our prediction for the Norwich vs Southampton match is: Southampton wins.
        Probabilities according to our algorithm* of possible 1X2 football predictions:
        The Sportytrader algorithm estimates a probability of 34.89% for a win of Norwich against Southampton with odds of 2.47.
        The probability according to Sportytrader for a draw between Norwich vs Southampton is 24.06% with odds of 3.82.
        Our prediction model gives a 41.05% chance for a win of Southampton vs Norwich with odds of 2.8.
        <h2>Norwich vs Southampton Form</h2> 83% BTTS 100% Over 2.5
        """
        row = sportytrader_detail(html, SPORTY_URL)
        self.assertEqual(row["provider_event_id"], "378798")
        self.assertAlmostEqual(row["prediction_1x2"]["home"], 34.89)
        self.assertAlmostEqual(row["prediction_1x2"]["draw"], 24.06)
        self.assertAlmostEqual(row["prediction_1x2"]["away"], 41.05)
        self.assertIsNone(row["goals_25"]["over"])
        self.assertIsNone(row["btts"]["yes"])
        self.assertEqual(row["identity_status"], "UNRESOLVED")

    def test_rejects_partial_triplet_as_null_not_guess(self):
        html = """<h1>Home vs Away Prediction</h1><div>Date 2026-10-14 18:00</div>
        <h4>Winner</h4> Home 82% Draw 11% Away 89%
        <h4>Total Goals 2.5</h4> Under 45% Over 55%
        <h4>Both Teams to Score BTTS</h4> Yes 54% No 46%
        <h4>Correct Score</h4> 1-0 13% <h2>Users Average</h2>"""
        row = betclan_detail(html, BETCLAN_URL)
        self.assertEqual(row["prediction_1x2"], {"home": None, "draw": None, "away": None})

    def test_links_are_provider_scoped_and_deduplicated(self):
        html = '<a href="/predictionsdetails/football/123/foo-v-bar-prediction/">a</a>' \
               '<a href="/predictionsdetails/football/123/foo-v-bar-prediction/">dup</a>' \
               '<a href="https://evil.invalid/predictionsdetails/football/22/x/">evil</a>'
        urls = extract_links("BETCLAN", html, "https://www.betclan.com/todays-football-predictions/")
        self.assertEqual(urls, ["https://www.betclan.com/predictionsdetails/football/123/foo-v-bar-prediction/"])
        self.assertEqual(extract_links("SPORTYTRADER",
            '<a href="/en/betting-tips/norwich-southampton-378798/">prediction</a>',
            "https://www.sportytrader.com/en/betting-tips/football/"),
            [SPORTY_URL])

    def test_capture_bounds_fail_closed(self):
        with self.assertRaises(ValueError):
            capture("BETCLAN", 10000)
        with self.assertRaises(ValueError):
            capture("SPORTYTRADER", 1, 0.01)


if __name__ == "__main__":
    unittest.main()
