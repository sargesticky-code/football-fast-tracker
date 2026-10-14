"""Offline Forebet V2 contract: no fake probability, wrong match or stale FS ID."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from playwright.sync_api import Error as BrowserError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from forebet_v2 import verified_rows, canonical_from_oidc, source_dates, dedupe_repeated_source_rows, source_overlap_diagnostics, run
from forebet_intersection_audit import source_intersection_audit, classify_target
from forebet_provisional import tentative_rows
from capture_forebet_canonical_light import league_ok, displayed_wall_clock
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

    def test_one_verified_team_and_league_time_is_only_provisional(self):
        row,target=sample()
        row["away_team"]="Man City Completely Unseen"
        candidates, stats = tentative_rows([row],[target],[],NOW)
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]["one_verified_side"],"HOME")
        self.assertEqual(candidates[0]["matched_identity"],
                         "ONE_SIDE_WITH_CONFIRMED_COMPETITION_AND_UNIQUE_KICKOFF")
        self.assertEqual(len(verified_rows([row],[target],NOW)[0]),0)
        self.assertEqual(stats["safe_one_side_provisionals"],1)
        self.assertEqual(tentative_rows([row],[target],
                         [{"match_id":target["match_id"]}],NOW)[0],[])

    def test_cross_league_and_wrong_kickoff_cannot_be_provisionally_accepted(self):
        row,target=sample()
        row["away_team"]="Unseen Visitors"
        row["league_short"]="It1"
        self.assertEqual(tentative_rows([row],[target],[],NOW)[0],[])
        row["league_short"]="EPL"
        row["kickoff_text"]="10/15/2026 02:10 PM"
        self.assertEqual(tentative_rows([row],[target],[],NOW)[0],[])
        row["kickoff_text"]="10/15/2026 02:00 PM"
        row["league_short"]="UNKNOWN_CODE"
        self.assertEqual(tentative_rows([row],[target],[],NOW)[0],[])

    def test_provisional_conflicting_source_identity_is_rejected(self):
        row,target=sample()
        row["away_team"]="Different Away"
        row2=dict(row, forebet_detail_url=
                  "https://www.forebet.com/en/football/matches/different-777777",
                  away_team="Another Away")
        self.assertEqual(tentative_rows([row,row2],[target],[],NOW)[0],[])
        other=dict(target,match_id="FS:othersafe1")
        self.assertEqual(tentative_rows([row],[target,other],[],NOW)[0],[])

    def test_provisional_both_verified_or_zero_verified_not_used(self):
        row,target=sample()
        self.assertEqual(tentative_rows([row],[target],[],NOW)[0],[])
        row["home_team"]="Unknown Side"
        row["away_team"]="Other Unknown Side"
        self.assertEqual(tentative_rows([row],[target],[],NOW)[0],[])
        row["home_team"]="Liverpool"
        row["away_team"]="The Unmatched Club"
        row["prob_home"]=None
        self.assertEqual(tentative_rows([row],[target],[],NOW)[0],[])

    def test_all_legacy_hkjc_connections_removed_from_active_repo(self):
        root=Path(__file__).resolve().parents[1]
        # A mistakenly re-added probe or manual workflow must fail even though
        # it has no schedule. Do not allow dormant scrapers to be re-enabled.
        for file in (root/".github"/"workflows").glob("*.yml"):
            self.assertNotIn("hkjc",file.read_text(encoding="utf-8").lower(),str(file))
        for relative in (
            "hkjc_live_market.py","vendor_hkjc_queries.py",
            "scripts/capture_hkjc_live_odds.py","scripts/normalize_hkjc.py",
            "scripts/update_hkjc_history.py",
            ".github/workflows/forebet_daily.yml"):
            self.assertFalse((root/relative).exists(),relative)
        active=(root/".github/workflows/supabase_private_ingest.yml").read_text(encoding="utf-8")
        self.assertIn("forebet-canonical-publish",active)
        self.assertIn("refs/heads/main",active)
        self.assertNotIn("hkjc",active.lower())
        self.assertNotIn("forebet-firecrawl-collector",active)


    def test_source_visible_complete_clock_can_cross_html_date_by_one_day_only(self):
        row,fixture=sample()
        row["match_date"]="2026-10-14"
        wall=displayed_wall_clock(row)
        self.assertEqual(wall.isoformat(),"2026-10-15T14:00:00")
        accepted,failures=verified_rows([row],[fixture],NOW)
        self.assertEqual(len(accepted),1,failures)
        row["match_date"]="2026-10-12"
        self.assertIsNone(displayed_wall_clock(row))
        self.assertEqual(verified_rows([row],[fixture],NOW)[0],[])

    def test_proven_championship_and_uefa_league_aliases_not_guess_other_leagues(self):
        self.assertTrue(league_ok("CH","Championship"))
        self.assertTrue(league_ok("CH","ChampionshipENGLAND: Standings"))
        self.assertTrue(league_ok("UCL","Champions League - League phase"))
        self.assertTrue(league_ok("UYL","UEFA Youth League - League phase"))
        self.assertTrue(league_ok("UYL","UEFA Youth League - Winners Play Offs"))
        self.assertTrue(league_ok("RuC","Russian Cup - Regions Path"))
        self.assertFalse(league_ok("UCL","Europa League - League phase"))
        self.assertFalse(league_ok("CH","Championship - Scotland"))
        self.assertFalse(league_ok("RuC","Premier League"))
        row,fixture=sample()
        row["league_short"]="CH"
        fixture["league"]="Championship"
        self.assertEqual(len(verified_rows([row],[fixture],NOW)[0]),1)
        fixture["league"]="EPL"
        self.assertEqual(verified_rows([row],[fixture],NOW)[0],[])


    def test_source_intersection_counts_each_fixture_once_without_faking_coverage(self):
        good,target=sample()
        unmatched=dict(target,match_id="FS:otherfixture",home="Other United",away="Unobserved FC")
        report=source_intersection_audit([good],[target,unmatched],
            [{"match_id":target["match_id"]}],NOW)
        self.assertEqual(report["fixture_denominator"],2)
        self.assertEqual(report["verified_published"],1)
        self.assertEqual(sum(report["unmatched_by_reason"].values()),1)
        self.assertIn("unobserved",report["scope_note"].lower())
        self.assertEqual(report["source_rows_input"],1)

    def test_forebet_pair_with_clock_disagreement_is_not_silently_accepted(self):
        source,target=sample()
        source["kickoff_text"]="10/15/2026 03:00 PM"
        issue,evidence=classify_target(target,[(source,
            datetime(2026,10,15,15,tzinfo=timezone.utc),True)],set())
        self.assertEqual(issue,"VERIFIED_PAIR_DIFFERENT_KICKOFF")
        self.assertIs(evidence,source)

    def test_forebet_known_league_conflict_does_not_increase_coverage(self):
        source,target=sample()
        source["league_short"]="It1"
        issue,_=classify_target(target,
            [(source,KO,True)],set())
        self.assertEqual(issue,"KNOWN_LEAGUE_CONFLICT")

    def test_missing_or_other_sources_are_not_reported_as_missing_forebet_products(self):
        source,target=sample()
        report=source_intersection_audit([], [target], [], NOW)
        self.assertEqual(report["unmatched_by_reason"],{
            "NO_SOURCE_OBSERVATION_AT_KICKOFF":1})
        source["away_team"]="Clearly Different Club"
        report=source_intersection_audit([source], [target], [], NOW)
        self.assertEqual(report["unmatched_by_reason"],{
            "ONE_VERIFIED_TEAM_AT_SAME_KICKOFF":1})

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


    def test_unknown_league_requires_both_independently_verified_provider_keys(self):
        fs,fb,by_key=shared_verified_catalog()
        couples=[]
        for name,key in fs.items():
            alternative=next((alias for alias in by_key.get(key,[])
                              if alias != name and len(alias)<35),None)
            if alternative:
                couples.append((name,alternative,key))
        (h,fh,hkey)=couples[0]
        (a,fa,akey)=next(item for item in couples if item[2]!=hkey)
        row,fixture=sample()
        row.update(home_team=fh,away_team=fa,league_short="UNREGISTERED_SOURCE")
        fixture.update(home=h,away=a)
        accepted,rejected=verified_rows([row],[fixture],NOW)
        self.assertEqual(len(accepted),1,rejected)
        self.assertEqual(accepted[0]["league_verification"],
                         "TWO_SHARED_PROVIDER_TEAM_KEYS_AND_UNIQUE_UTC_FIXTURE")
        self.assertEqual(accepted[0]["identity_method"],
                         "TWO_SHARED_PROVIDER_KEYS_UNKNOWN_LEAGUE_EXACT_UTC_TIME")
        row["away_team"]="Unknown Fictional Club"
        self.assertEqual(verified_rows([row],[fixture],NOW)[0],[])
        row["away_team"]=fa
        row["kickoff_text"]="10/15/2026 02:03 PM"
        self.assertEqual(verified_rows([row],[fixture],NOW)[0],[])
        row["kickoff_text"]="10/15/2026 02:00 PM"
        row["league_short"]="It1"
        self.assertEqual(verified_rows([row],[fixture],NOW)[0],[])

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
