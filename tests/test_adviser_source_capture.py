import unittest
from scripts.adviser_source_capture import parse_betclan, parse_sportytrader, candidate_urls, valid_triplet


class AdviserSourceCaptureTest(unittest.TestCase):
    def test_betclan_genuine_detail_shape(self):
        html = """<h1>QPR vs Derby Prediction, H2H, Tip and Match Preview</h1>
        <p>Date 2026-10-14 19:45</p><h4>Winner</h4>
        <p>QPR Home 57% Draw 23% Away 20%</p>
        <h4>Total Goals 2.5</h4><p>Under 44% Over 56%</p>
        <h4>Both Teams to Score BTTS</h4><p>Yes 58% No 42%</p>
        <h4>Correct Score</h4><p>3-1 13% Others 87%</p>
        <h3>Team Momentum</h3>"""
        row = parse_betclan(html, "https://www.betclan.com/predictionsdetails/football/1563202/qpr-v-derby-prediction/")
        self.assertEqual(row["hda"], {"home": 0.57, "draw": 0.23, "away": 0.2})
        self.assertEqual(row["predicted_score"], "3-1")
        self.assertEqual(row["over25"], 0.56)
        self.assertEqual(row["btts_yes"], 0.58)
        self.assertIsNone(row["canonical_event_id"])
        self.assertFalse(row["kickoff_timezone_verified"])

    def test_sportytrader_tip_is_not_fake_probability(self):
        html = """<h1>QPR vs Derby County Prediction & Betting Tips - Championship</h1>
          <div>15/10/2026 07:45</div><p>Prediction : BTTS 1.83</p>
          <p>Prediction published on 14/10/2026</p>"""
        row = parse_sportytrader(html, "https://www.sportytrader.com/en/betting-tips/qpr-derby-county-378837/")
        self.assertEqual(row["tip"], "BTTS")
        self.assertEqual(row["source_date"], "2026-10-15")
        self.assertIsNone(row["hda"])
        self.assertEqual(row["identity"], "UNRESOLVED")

    def test_source_boundary(self):
        html = """<a href="/predictionsdetails/football/123/abc">One</a>
           <a href="https://evil.test/predictionsdetails/football/999/bad">Evil</a>"""
        self.assertEqual(len(candidate_urls(html, "BETCLAN")), 1)

    def test_wrong_probability_triplet_rejected(self):
        self.assertIsNone(valid_triplet({"home": .8, "draw": .4, "away": .3}))


if __name__ == "__main__":
    unittest.main()
