"""No-network regression tests for strict source-to-canonical Forebet mapping."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from forebet_canonical_source_probe import (  # noqa: E402
    aware_time, build_verified_rows, canonical_targets, model_fields,
)
from scrape_forebet import parse_forebet_rows  # noqa: E402

NOW = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)
KICK = datetime(2026, 10, 10, 19, 30, tzinfo=timezone.utc)

def fixture(name="Arsenal", away="Leeds", match_id="FB6342"):
    return {"match_id": match_id, "kickoff": KICK,
            "home": name, "away": away, "league": "EPL"}

def source(source_kickoff_iso="2026-10-10T19:30:00+00:00"):
    return {
        "source_kickoff_iso": source_kickoff_iso,
        "home_team": "Arsenal", "away_team": "Leeds",
        "prob_home": 61, "prob_draw": 24, "prob_away": 15,
        "prediction_1x2": "1", "predicted_score": "2 - 1",
        "avg_goals": "3.14", "forebet_detail_url":
        "https://www.forebet.com/en/football/matches/arsenal-leeds-1",
        "match_date": "2026-10-10", "kickoff_text": "19:30",
        "league_short": "EPL",
    }

class StrictCanonicalForebetTests(unittest.TestCase):
    def test_only_provider_aware_timestamp(self):
        self.assertIsNone(aware_time("2026-10-10 19:30:00"))
        self.assertIsNone(aware_time("2026-10-10"))
        self.assertEqual(aware_time("2026-10-10T20:30:00+01:00"), KICK)

    def test_strict_unique_identity_and_all_required_predictions(self):
        matches = [fixture()]
        row = build_verified_rows(matches, [source()], NOW)
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0]["match_id"], "FB6342")
        self.assertEqual(row[0]["avg_goals"], 3.14)
        self.assertEqual(row[0]["score"], "2 - 1")
        self.assertEqual(row[0]["identity_method"], "EXACT_TEAMS_AND_PROVIDER_TIME")

    def test_no_fuzzy_names_no_wrong_time_no_ambiguity(self):
        self.assertEqual(build_verified_rows([fixture()], [source("2026-10-10T20:00:00Z")], NOW), [])
        altered = source()
        altered["home_team"] = "Arsenal Women"
        self.assertEqual(build_verified_rows([fixture()], [altered], NOW), [])
        self.assertEqual(build_verified_rows([fixture()], [source(), source()], NOW), [])
        self.assertEqual(build_verified_rows([fixture(), fixture(match_id="FS:duplicate")], [source()], NOW), [])

    def test_no_stale_or_invalid_model(self):
        self.assertEqual(build_verified_rows([fixture()], [source("2026-10-10 19:30")], NOW), [])
        r = source()
        r["avg_goals"] = ""
        self.assertIsNone(model_fields(r))
        r = source()
        r["prob_home"] = "100"
        self.assertIsNone(model_fields(r))
        r = source()
        r["forebet_detail_url"] = "http://other.invalid/match"
        self.assertIsNone(model_fields(r))

    def test_bound_fixture_universe(self):
        fixtures = [{"id": "FB6342", "kickoff": KICK.isoformat(), "home": "Arsenal", "away": "Leeds", "league": "EPL"}]
        self.assertEqual(len(canonical_targets(fixtures, NOW)), 1)
        self.assertEqual(canonical_targets(fixtures, NOW + timedelta(days=2)), [])
        with self.assertRaisesRegex(ValueError, "bounded limit"):
            canonical_targets(fixtures * 351, NOW)

    def test_reuse_existing_html_parser_and_preserve_source_time(self):
        html = """
        <div class="rcnt">
          <span class="homeTeam"><span itemprop="name">Arsenal</span></span>
          <span class="awayTeam"><span itemprop="name">Leeds</span></span>
          <time datetime="2026-10-10T19:30:00+00:00"></time>
          <div class="fprc"><span>61</span><span>24</span><span>15</span></div>
          <span class="forepr"><span>1</span></span>
          <div class="ex_sc tabonly">2 - 1</div>
          <div class="avg_sc tabonly">3.14</div>
          <a href="/en/football/matches/arsenal-leeds-1">Details</a>
        </div>
        """
        parsed = parse_forebet_rows(html, "2026-10-10")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["source_kickoff_iso"], "2026-10-10T19:30:00+00:00")
        self.assertEqual(len(build_verified_rows([fixture()], parsed, NOW)), 1)

if __name__ == "__main__":
    unittest.main()
