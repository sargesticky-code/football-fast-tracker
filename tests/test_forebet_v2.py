"""Offline Forebet V2 contract: no fake probability, wrong match or stale FS ID."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from playwright.sync_api import Error as BrowserError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from forebet_v2 import verified_rows, canonical_from_oidc, source_dates, dedupe_repeated_source_rows, source_overlap_diagnostics, run
from forebet_verified_aliases import (shared_verified_catalog, source_forms,
                                      verified_source_name, norm, verified_shared_source_name)

NOW=datetime(2026,10,14,3,0,tzinfo=timezone.utc)
KO=datetime(2026,10,15,14,0,tzinfo=timezone.utc)

def sample():
    row={"home_team":"Liverpool","away_team":"Manchester City",
        "league_short":"EPL","match_date":"2026-10-15",
        "kickoff_text":"10/15/2026 02:00 PM","prob_home":32,
        "prob_draw":28,"prob_away":40,"prediction_1x2":"2",
        "predicted_score":"1 - 2","avg_goals":"2.73",
        "forebet_detail_url":"https://www.forebet.com/en/football/matches/liverpool-mancity-123456"}
    fixture={"match_id":"FS:safefix1","home":"Liverpool","away":"Manchester City",
        "league":"EPL","kickoff":KO}
    return row,fixture

class SourceIdentityTests(unittest.TestCase):

    def test_cross_source_snapshot_is_complete_and_without_provider_api(self):
        fs,fb,by_key=shared_verified_catalog()
        self.assertGreaterEqual(len(fs),500)
        self.assertGreaterEqual(len(fb),550)
        self.assertGreaterEqual(len(by_key),500)
        self.assertTrue(all(len(key)==32 for key in by_key))

    def test_verified_bridge_accepts_only_same_proven_team_key(self):
        fs,fb,by_key=shared_verified_catalog()
        proof = next(((f,a) for f,key in fs.items()
                      for a in by_key.get(key,[]) if a!=f),None)
        self.assertIsNotNone(proof)
        flashscore,forebet=proof
        self.assertIn(forebet,source_forms(flashscore))
        self.assertTrue(verified_shared_source_name(forebet,flashscore))
        self.assertTrue(verified_source_name(forebet,flashscore))
        false_name=next(name for name,key in fb.items()
                        if key!=fs[flashscore] and name!=flashscore)
        self.assertFalse(verified_shared_source_name(false_name,flashscore))
        self.assertFalse(verified_source_name(false_name,flashscore))

    def test_bridge_keeps_exact_name_working_when_missing_from_registry(self):
        self.assertTrue(verified_source_name("Never Seen Town","Never Seen Town"))
        self.assertIn(norm("Never Seen Town"),source_forms("Never Seen Town"))

    def test_single_unique_exact_match_no_cohort_requirement(self):
        row,fixture=sample()
        accepted,rejected=verified_rows([row],[fixture],NOW)
        self.assertEqual(rejected,{})
        self.assertEqual(len(accepted),1)
        self.assertEqual(accepted[0]["match_id"],fixture["match_id"])
        self.assertEqual(accepted[0]["score"],"1 - 2")
        self.assertEqual(accepted[0]["avg_goals"],2.73)
        self.assertEqual(accepted[0]["source_display_offset_minutes"],0)

    def test_stale_or_wrong_kickoff_rejected(self):
        row,fixture=sample()
        row["kickoff_text"]="10/15/2026 03:00 PM"
        rows,bad=verified_rows([row],[fixture],NOW)
        self.assertEqual(rows,[])
        self.assertEqual(bad["CLOCK_OFFSET_CHANGED_OR_WRONG_FIXTURE"],1)

    def test_wrong_league_or_reversed_team_rejected(self):
        row,fixture=sample()
        row["league_short"]="It1"
        self.assertEqual(verified_rows([row],[fixture],NOW)[0],[])
        row,fixture=sample()
        row["home_team"],row["away_team"]=row["away_team"],row["home_team"]
        self.assertEqual(verified_rows([row],[fixture],NOW)[0],[])

    def test_no_probabilities_or_no_avg_goal_never_zero(self):
        row,fixture=sample()
        row["avg_goals"]=None
        self.assertEqual(verified_rows([row],[fixture],NOW)[0],[])
        row,fixture=sample()
        row["prob_home"]=None
        self.assertEqual(verified_rows([row],[fixture],NOW)[0],[])

    def test_duplicate_identity_rejected(self):
        row,fixture=sample()
        rows,bad=verified_rows([row,dict(row)],[fixture],NOW)
        self.assertEqual(rows,[])
        self.assertEqual(bad["DUPLICATE_SOURCE_OR_CANONICAL_EVENT"],1)

    def test_unknown_league_only_exact_names_and_exact_time(self):
        row,fixture=sample()
        row["league_short"]="Us1"
        matched,_=verified_rows([row],[fixture],NOW)
        self.assertEqual(len(matched),1)
        self.assertEqual(matched[0]["league_verification"],"EXACT_NAMES_AND_UTC_TIME_ONLY")
        row["home_team"]="Liverpoool"
        self.assertEqual(verified_rows([row],[fixture],NOW)[0],[])

    def test_three_duplicate_rows_never_readmit_fixture(self):
        row,fixture=sample()
        out,_=verified_rows([row,dict(row),dict(row)],[fixture],NOW)
        self.assertEqual(out,[])

    def test_source_dates_follow_utc_kickoffs_not_hkt_midnight(self):
        fixtures = [
            {"kickoff": NOW + timedelta(hours=2)},
            {"kickoff": NOW + timedelta(hours=24)},
            {"kickoff": NOW + timedelta(hours=47)},
        ]
        self.assertEqual(source_dates(fixtures,NOW),
                         ["2026-10-14","2026-10-15","2026-10-16"])

    def test_deduplicate_same_page_row_but_not_conflicting_model(self):
        row, fixture = sample()
        clone = dict(row)
        changed = dict(row)
        changed["prob_home"] = 31
        result = dedupe_repeated_source_rows([row,clone,changed])
        self.assertEqual(len(result),2)
        accepted, errors = verified_rows(result,[fixture],NOW)
        self.assertEqual(accepted,[])
        self.assertEqual(errors["DUPLICATE_SOURCE_OR_CANONICAL_EVENT"],1)

    def test_source_dates_fail_on_no_fixtures(self):
        with self.assertRaisesRegex(ValueError,"SOURCE_DATE_WINDOW_OUT_OF_BOUNDS"):
            source_dates([],NOW)

    def test_source_qa_distinguishes_missing_event_from_possible_alias(self):
        source, fixture = sample()
        self.assertEqual(
            source_overlap_diagnostics([source], [fixture], NOW)
              ["exact_team_pair_and_kickoff"], 1)
        other = dict(source, home_team="Different Town", away_team="Other United")
        self.assertEqual(
            source_overlap_diagnostics([other], [fixture], NOW)
              ["no_exact_team_at_same_kickoff"], 1)
        past = dict(source, kickoff_text="10/13/2026 02:00 PM",
                    match_date="2026-10-13")
        self.assertEqual(
            source_overlap_diagnostics([past], [fixture], NOW)
              ["outside_48h_verified_fixture_window"], 1)

    def test_browser_failure_is_scoped_to_one_date_not_a_false_success(self):
        row, fixture = sample()
        # The real pipeline will only publish strictly verified rows from the
        # second page when the first source date was unavailable.
        targets = [
            dict(fixture, match_id=f"FS:unique{i}", home=f"Home{i}",
                 away=f"Away{i}",kickoff=NOW+timedelta(hours=i+1))
            for i in range(8)
        ] + [fixture]
        def browser(url, date, target_rows, helper):
            if date=="2026-10-14":
                raise BrowserError("navigation timed out")
            return [row], {
                "initial":1, "expanded":1, "matched":1,
                "parsed_candidates":1, "capture_mode":"full_page",
                "rendered_html_bytes":500, "expand_clicked":False
            }
        with patch("forebet_v2.canonical_from_oidc",return_value=targets), \
             patch("forebet_v2.load_canonical_candidates",side_effect=browser):
            proof=run(now=NOW,fixture_token="t"*60)
        self.assertEqual(proof["pages_attempted"],2)
        self.assertEqual(proof["pages_successful"],1)
        self.assertTrue(proof["partial_source_coverage"])
        self.assertEqual(proof["strict_verified_models"],1)
        self.assertEqual(proof["pages_failed"][0]["error"],"Error")

    def test_requires_verified_provider_not_plain_fixture_snapshot(self):
        class Session:
            def get(self,*args,**kwargs):
                class R:
                    def raise_for_status(self):pass
                    def json(self):
                        return {"source":"hkjc-authority-snapshot",
                            "generatedAt":NOW.isoformat(),"matches":[]}
                return R()
        with self.assertRaisesRegex(ValueError,"NOT_FLASHScore_VERIFIED"):
            canonical_from_oidc("t"*60,NOW,Session())

if __name__=="__main__":
    unittest.main()
