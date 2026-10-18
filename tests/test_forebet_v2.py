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
from forebet_league_cohort import verified_competition_cohorts
from capture_forebet_canonical_light import league_ok, displayed_wall_clock
from forebet_verified_aliases import (shared_verified_catalog, native_verified_catalog, source_forms,
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

    def test_new_native_flashscore_alias_snapshot_is_offline_and_strict(self):
        source_ids,target_ids,forms=native_verified_catalog()
        self.assertEqual(len(source_ids),254)
        self.assertGreaterEqual(len(target_ids),240)
        self.assertEqual(source_ids[norm("Leeds United")],target_ids[norm("Leeds")])
        self.assertTrue(verified_source_name("Leeds United","Leeds"))
        self.assertTrue(verified_source_name("Manchester United","Manchester Utd"))
        self.assertTrue(verified_source_name("Deportivo Toluca","Toluca"))
        self.assertTrue(verified_source_name("Atlético San Luis","Atl. San Luis"))
        self.assertIn(norm("Leeds United"),source_forms("Leeds"))
        self.assertIn(norm("Manchester United"),source_forms("Manchester Utd"))
        self.assertFalse(verified_source_name("Leeds United","Manchester Utd"))
        self.assertFalse(verified_source_name("Deportivo Toluca","Manchester Utd"))


    def test_verified_flashscore_scope_accepts_600_and_fails_closed_above_cap(self):
        class Response:
            def __init__(self, payload):
                self.payload = payload
            def raise_for_status(self):
                pass
            def json(self):
                return self.payload
        class Session:
            def __init__(self, payload):
                self.payload = payload
            def get(self, *args, **kwargs):
                return Response(self.payload)
        context = {"identityStatus":"EXACT_CANONICAL_PROVIDER_FIXTURE",
                   "provider":"FLASHSCORE"}
        fixtures = [
            {"id":f"FS:cap{i:08d}","home":f"Home {i}","away":f"Away {i}",
             "league":"Test League","kickoff":(NOW+timedelta(hours=3, minutes=i % 10)).isoformat(),
             "sourceContext":context}
            for i in range(600)
        ]
        payload = {"source":"flashscore-verified-canonical-fixtures-v2",
                   "generatedAt":NOW.isoformat(), "matches":fixtures}
        self.assertEqual(len(canonical_from_oidc("o"*51, NOW, Session(payload))),600)
        payload["matches"] = fixtures + [{
            **fixtures[0], "id":"FS:overcap001"}]
        with self.assertRaisesRegex(ValueError, "INVALID_VERIFIED_CANONICAL_FIXTURES"):
            canonical_from_oidc("o"*51, NOW, Session(payload))

    def test_unknown_league_self_corrobates_only_from_three_exact_strict_fixtures(self):
        source,targets,strict=[],[],[]
        for i in range(3):
            r,t=sample()
            h,a="Cohort Home "+str(i),"Cohort Away "+str(i)
            ko=KO+timedelta(hours=i)
            url="https://www.forebet.com/en/football/matches/league-cohort-"+str(700001+i)
            r.update(home_team=h,away_team=a,league_short="QFC",
                     forebet_detail_url=url,kickoff_text=ko.strftime("%m/%d/%Y %I:%M %p"))
            t.update(match_id="FS:cohort"+str(i),home=h,away=a,league="FA Cup - Qualification",kickoff=ko)
            source.append(r);targets.append(t)
            strict.append({"match_id":t["match_id"],"source_league":"QFC",
              "source_event_url":url,"league_verification":"EXACT_NAMES_AND_UTC_TIME_ONLY"})
        r,t=sample()
        r.update(home_team="Cohort Last Home",away_team="One Sided Unknown",
                 league_short="QFC",
                 forebet_detail_url="https://www.forebet.com/en/football/matches/last-701000",
                 kickoff_text=(KO+timedelta(hours=3)).strftime("%m/%d/%Y %I:%M %p"))
        t.update(match_id="FS:cohortlast",home="Cohort Last Home",
                 away="Canonical Last Away",league="FA Cup - Qualification",
                 kickoff=KO+timedelta(hours=3))
        source.append(r);targets.append(t)
        self.assertEqual(verified_competition_cohorts(source,targets,strict),
                         {"QFC":"FA Cup - Qualification"})
        provisional,stats=tentative_rows(source,targets,strict,NOW)
        self.assertEqual(len(provisional),1)
        self.assertEqual(provisional[0]["match_id"],t["match_id"])
        self.assertEqual(provisional[0]["league_verification"],
                         "SAME_CAPTURE_3_STRICT_TWO_TEAM_FIXTURES")
        self.assertEqual(stats["cohort_based_provisionals"],1)
        # Two strict fixtures do not establish competition provenance.
        self.assertFalse(tentative_rows(source,targets,strict[:2],NOW)[0])
        # Contradiction anywhere in the cohort invalidates all proposals.
        mismatched=[dict(x) for x in targets]
        mismatched[1]["league"]="FA Cup - Final"
        self.assertFalse(verified_competition_cohorts(source,mismatched,strict))
        self.assertFalse(tentative_rows(source,mismatched,strict,NOW)[0])
        # The inferred code must not be used for a different league.
        wrong=[dict(x) for x in targets]
        wrong[-1]["league"]="Premier League"
        self.assertFalse(tentative_rows(source,wrong,strict,NOW)[0])
        # Source home/away remains ordered even when league is corroborated.
        flipped=[dict(x) for x in source]
        flipped[-1]["home_team"],flipped[-1]["away_team"]=(
            flipped[-1]["away_team"],flipped[-1]["home_team"])
        self.assertFalse(tentative_rows(flipped,targets,strict,NOW)[0])

    def test_fuzzy_name_floor_030_remains_tentative_and_never_strict(self):
        row,target=sample()
        row["home_team"]="Liverpoolz"     # 10/11 chars, verified alias unknown
        row["away_team"]="Man Ct"        # weak but >=30% name similarity
        rows,stats=tentative_rows([row],[target],[],NOW)
        self.assertEqual(len(rows),1,stats)
        candidate=rows[0]
        self.assertEqual(candidate["one_verified_side"],"SIMILARITY")
        self.assertEqual(candidate["matched_identity"],
                         "BOTH_NAME_SIMILARITY_030_STRONG_SIDE_070_LEAGUE_EXACT_TIME_UNIQUE")
        self.assertGreaterEqual(min(candidate["home_similarity"],
                                    candidate["away_similarity"]),0.30)
        self.assertGreaterEqual(max(candidate["home_similarity"],
                                    candidate["away_similarity"]),0.70)
        self.assertEqual(stats["fuzzy_both_name_provisionals"],1)
        self.assertEqual(stats["safe_one_side_provisionals"],0)
        self.assertFalse(verified_rows([row],[target],NOW)[0])

    def test_fuzzy_does_not_accept_wrong_or_ambiguous_matches(self):
        row,target=sample()
        row.update(home_team="Liverpoolz",away_team="Man Ct")
        def matches(changed,targets=None):
            return tentative_rows([changed],targets or [target],[],NOW)[0]
        self.assertFalse(matches(dict(row,league_short="It1")))
        self.assertFalse(matches(dict(row,kickoff_text="10/15/2026 02:03 PM")))
        self.assertFalse(matches(dict(row,home_team="Another Club")))
        self.assertFalse(matches(dict(row,away_team="Other Unknown Wanderers")))
        self.assertFalse(matches(dict(row,home_team="Man Ct",away_team="Liverpoolz")))
        other=dict(target,match_id="FS:duplicatefixture")
        self.assertFalse(matches(row,[target,other]))
        self.assertFalse(tentative_rows([row,dict(row,
           forebet_detail_url="https://www.forebet.com/en/football/matches/second-700001")],
           [target],[],NOW)[0])

    def test_one_verified_side_takes_priority_over_weaker_030_suggestion(self):
        row,target=sample()
        row["away_team"]="Totally Unseen"
        fuzzy=dict(row,home_team="Liverpoolz",away_team="Man Ct",
                   forebet_detail_url="https://www.forebet.com/en/football/matches/fuzzy-701123")
        rows,stats=tentative_rows([row,fuzzy],[target],[],NOW)
        self.assertEqual(len(rows),1,stats)
        self.assertEqual(rows[0]["one_verified_side"],"HOME")
        self.assertEqual(stats["fuzzy_both_name_provisionals"],0)
        self.assertEqual(rows[0]["source_url"],row["forebet_detail_url"])

    def test_fuzzy_capacity_prefers_verified_side_and_marks_source_incomplete(self):
        rows=[];targets=[]
        for i in range(3):
            row,fixture=sample()
            at=KO+timedelta(hours=i)
            row["kickoff_text"]=at.strftime("%m/%d/%Y %I:%M %p")
            row["forebet_detail_url"]=(
                "https://www.forebet.com/en/football/matches/limit-"+str(700100+i))
            fixture["kickoff"]=at
            fixture["match_id"]="FS:capfuzzy"+str(i)
            if i==0:
                row["away_team"]="Unknown Team A"
            else:
                row["home_team"]="Liverpoolz"
                row["away_team"]="Man Ct"
            rows.append(row);targets.append(fixture)
        with patch("forebet_provisional.MAX_PROVISIONALS",2):
            candidates,stats=tentative_rows(rows,targets,[],NOW)
        self.assertEqual(len(candidates),2)
        self.assertTrue(stats["fuzzy_capacity_limited"])
        self.assertEqual(stats["fuzzy_truncated_count"],1)
        self.assertEqual(stats["safe_one_side_provisionals"],1)
        self.assertEqual(stats["fuzzy_both_name_provisionals"],1)
        self.assertIn("FS:capfuzzy0",{x["match_id"] for x in candidates})

    def test_one_side_accepted_for_display_but_known_opponent_conflict_rejected(self):
        row,target=sample()
        row["away_team"]="New Unknown Away"
        accepted,stats=tentative_rows([row],[target],[],NOW)
        self.assertEqual(len(accepted),1,stats)
        self.assertEqual(accepted[0]["one_verified_side"],"HOME")
        self.assertEqual(accepted[0]["matched_identity"],
                         "ONE_SIDE_WITH_CONFIRMED_COMPETITION_AND_UNIQUE_KICKOFF")
        # The other side is unknown, not independently verified. If the
        # offline provider registry explicitly contradicts it, disconnect.
        with patch("forebet_provisional.verified_shared_source_name",return_value=False):
            refused,stats=tentative_rows([row],[target],[],NOW)
        self.assertEqual(refused,[])
        self.assertEqual(stats["verified_opponent_contradiction"],1)
        # One-team match never becomes two-team verified model evidence.
        self.assertEqual(verified_rows([row],[target],NOW)[0],[])

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
        for relative in ("api/live_scores.py", "vercel.json"):
            self.assertNotIn("hkjc", (root/relative).read_text(encoding="utf-8").lower(),relative)
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

    def test_short_flashscore_competition_names_are_exact_not_fuzzy(self):
        expected = {
            "EPL":"Premier League",
            "Es1":"LaLiga",
            "It1":"Serie A",
            "De1":"Bundesliga",
            "Fr1":"Ligue 1",
            "Ar1":"Liga Profesional - Clausura",
            "Cz1":"Chance Liga",
            "L1":"League One",
            "L2":"League Two",
            "Th1":"Thai League 1",
            "Fr2":"Ligue 2",
            "De2":"2. Bundesliga",
            "Es2":"LaLiga2",
        }
        for source,canonical in expected.items():
            with self.subTest(source=source, canonical=canonical):
                self.assertTrue(league_ok(source,canonical))
                self.assertFalse(league_ok(source,canonical+" Other"))
                self.assertFalse(league_ok(source,"Totally Different League"))
        self.assertFalse(league_ok("Fr1","Serie A"))
        self.assertFalse(league_ok("It1","Ligue 1"))

    def test_provisional_cross_league_one_side_can_never_promote_directly(self):
        row,fixture=sample()
        row["league_short"]="Th1"
        row["away_team"]="Unknown away team"
        fixture["league"]="Thai League 1"
        preview,_=tentative_rows([row],[fixture],[],NOW)
        self.assertEqual(len(preview),1)
        self.assertEqual(preview[0]["one_verified_side"],"HOME")
        self.assertFalse(verified_rows([row],[fixture],NOW)[0])
        # Changing the venue, clock or league invalidates the proposal.
        self.assertFalse(tentative_rows([dict(row,league_short="L1")],[fixture],[],NOW)[0])
        wrong=dict(fixture,league="Premier League")
        self.assertFalse(tentative_rows([row],[wrong],[],NOW)[0])
        self.assertFalse(tentative_rows([dict(row,kickoff_text="10/15/2026 03:00 PM")],[fixture],[],NOW)[0])
        self.assertFalse(tentative_rows([dict(row,home_team="unknown",away_team="Liverpool")],[fixture],[],NOW)[0])

    def test_short_league_names_reject_other_countries_and_similar_titles(self):
        for code,title,wrong in (
            ("Cz1","Chance Liga","Liga Portugal"),
            ("L1","League One","League One - Scotland"),
            ("L2","League Two","League One"),
            ("Th1","Thai League 1","Thai League 2"),
            ("Fr2","Ligue 2","Ligue 1"),
            ("De2","2. Bundesliga","Bundesliga"),
            ("Es2","LaLiga2","LaLiga"),
        ):
            with self.subTest(code=code):
                self.assertTrue(league_ok(code,title))
                self.assertFalse(league_ok(code,wrong))
                self.assertFalse(league_ok(code,title+" - OTHER"))

    def test_current_short_league_still_requires_exact_pair_and_time(self):
        row,fixture=sample()
        fixture["league"]="Premier League"
        accepted,_=verified_rows([row],[fixture],NOW)
        self.assertEqual(len(accepted),1)
        self.assertEqual(accepted[0]["match_id"],fixture["match_id"])
        self.assertEqual(accepted[0]["source_league"],"EPL")
        swapped=dict(row,home_team=row["away_team"],away_team=row["home_team"])
        self.assertEqual(verified_rows([swapped],[fixture],NOW)[0],[])
        wrong_time=dict(row,kickoff_text="10/15/2026 03:00 PM")
        self.assertEqual(verified_rows([wrong_time],[fixture],NOW)[0],[])
        wrong_league=dict(row,league_short="It1")
        self.assertEqual(verified_rows([wrong_league],[fixture],NOW)[0],[])

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
        def browser(url, date, target_rows, helper, parser=None):
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
