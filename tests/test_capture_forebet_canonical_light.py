import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from capture_forebet_canonical_light import verified_rows,displayed_utc,league_ok,source_coverage_counts,canonical_feed_matches

NOW=datetime(2026,10,10,14,10,tzinfo=timezone.utc)
GROUPS=[("EPL","EPL"),("Es1","LaLigaSPAIN: Standings"),("It1","Serie AITALY: Standings")]
def examples(n=12):
    fixtures=[];rows=[]
    for i in range(n):
        source,canon=GROUPS[i%3]
        kickoff=datetime(2026,10,11,13+(i//6),i%6*10,tzinfo=timezone.utc)
        home=f"Sample Home {i}"
        away=f"Sample Away {i}"
        fixtures.append({"match_id":f"FS:example{i}","kickoff":kickoff,"home":home,"away":away,"league":canon})
        rows.append({"home_team":home,"away_team":away,"league_short":source,
                     "match_date":"2026-10-11",
                     "kickoff_text":kickoff.strftime("%m/%d/%Y %I:%M %p"),
                     "prob_home":40.0,"prob_draw":30.0,"prob_away":30.0,
                     "prediction_1x2":"1","predicted_score":"2 - 1",
                     "avg_goals":"2.63",
                     "forebet_detail_url":f"https://www.forebet.com/en/football/matches/test-{i}"})
    return rows,fixtures

class StrictCaptureTests(unittest.TestCase):
    def test_global_dom_count_is_not_canonical_rejection_denominator(self):
        rows, fixtures = examples()
        accepted, _ = verified_rows(rows[:10], fixtures, NOW)
        proof = source_coverage_counts(
            {"expanded":1115,"matched":12,"parsed_candidates":12},
            fixtures,"2026-10-11",rows,accepted
        )
        self.assertEqual(proof["source_dom_rows_expanded"],1115)
        self.assertEqual(proof["normalized_candidate_rows"],12)
        self.assertEqual(proof["strict_accepted_candidate_rows"],10)
        self.assertEqual(proof["candidate_rows_not_accepted"],2)
        self.assertEqual(proof["canonical_targets_on_captured_day"],12)
        self.assertEqual(proof["canonical_targets_on_other_days"],0)
        self.assertEqual(proof["accounting_semantics"],"DOM_GLOBAL_VS_PRE_FILTERED_CANDIDATES")

    def test_live_cohort_requires_multiple_distinct_leagues(self):
        rows,fx=examples()
        matched,info=verified_rows(rows,fx,NOW)
        self.assertEqual(info["verified"],12)
        self.assertEqual(len(matched),12)
        self.assertTrue(all(x["identity_method"]=="EXACT_TEAMS_LEAGUE_AND_CORROBORATED_TIME" for x in matched))
        self.assertTrue(all(x["avg_goals"]==2.63 for x in matched))
    def test_fail_closed_on_single_match(self):
        rows,fx=examples()
        matched,info=verified_rows(rows[:1],fx,NOW)
        self.assertEqual(matched,[])
        self.assertEqual(info["reason"],"COHORT_TIME_NOT_CORROBORATED")
    def test_cross_league_rejected(self):
        rows,fx=examples()
        rows[0]["league_short"]="Fr1"
        matched,info=verified_rows(rows,fx,NOW)
        self.assertEqual(len(matched),11)
    def test_ambiguous_duplicated_identity_not_published(self):
        rows,fx=examples()
        rows.append(dict(rows[0]))
        matched,info=verified_rows(rows,fx,NOW)
        self.assertEqual(matched,[])
        self.assertEqual(info["reason"],"COHORT_TIME_NOT_CORROBORATED")
    def test_wrong_kickoff_rejected(self):
        rows,fx=examples()
        rows[0]["kickoff_text"]="10/11/2026 11:11 PM"
        matched,info=verified_rows(rows,fx,NOW)
        self.assertEqual(len(matched),11)
    def test_reversed_fixture_rejected(self):
        rows,fx=examples()
        rows[0]["home_team"],rows[0]["away_team"]=rows[0]["away_team"],rows[0]["home_team"]
        matched,info=verified_rows(rows,fx,NOW)
        self.assertEqual(len(matched),11)
    def test_no_zero_substitute_missing_avg_goals(self):
        rows,fx=examples()
        rows[0]["avg_goals"]=None
        matched,info=verified_rows(rows,fx,NOW)
        self.assertEqual(len(matched),11)
    def test_displayed_time_must_have_date_and_clock(self):
        row={"match_date":"2026-10-11","kickoff_text":"2026-10-11"}
        self.assertIsNone(displayed_utc(row))
        row["kickoff_text"]="10/11/2026 02:10 PM"
        self.assertEqual(displayed_utc(row).isoformat(),"2026-10-11T14:10:00+00:00")
    def test_observed_corroborated_competition_codes(self):
        proven = {
            "Bg1": "efbet LeagueBULGARIA: Standings",
            "Cz1": "Chance LigaCZECH REPUBLIC: Standings",
            "Gr1": "Super LeagueGREECE: Standings",
            "Hr1": "HNLCROATIA: Standings",
            "Ar1": "Liga Profesional - ClausuraARGENTINA: Standings",
            "Cl1": "Liga de PrimeraCHILE: Standings",
            "Bo1": "Division ProfesionalBOLIVIA: Standings",
        }
        for code, competition in proven.items():
            with self.subTest(code=code):
                self.assertTrue(league_ok(code, competition))
                self.assertFalse(league_ok(code, "EPL"))
                self.assertFalse(league_ok(code, "Serie AITALY: Standings"))
                self.assertFalse(league_ok("unverified", competition))

    def test_registry_alias_preserves_original_forebet_names(self):
        rows,fx=examples()
        fx[0]["home"]="Manchester Utd"
        rows[0]["home_team"]="Manchester United"
        fx[2]["away"]="AC Milan"
        rows[2]["away_team"]="Milan"
        result,info=verified_rows(rows,fx,NOW)
        self.assertEqual(len(result),12)
        self.assertEqual(info["verified_alias_matches"],2)
        mapped={r["match_id"]:r for r in result}
        self.assertEqual(mapped["FS:example0"]["source_home"],"Manchester United")
        self.assertEqual(mapped["FS:example0"]["canonical_home"],"Manchester Utd")
        self.assertEqual(mapped["FS:example2"]["source_away"],"Milan")
        self.assertEqual(mapped["FS:example2"]["canonical_away"],"AC Milan")
        self.assertEqual(mapped["FS:example0"]["match_score"],0.985)
        self.assertEqual(mapped["FS:example0"]["identity_method"],
                         "VERIFIED_ALIAS_LEAGUE_AND_CORROBORATED_TIME")
    def test_unverified_fake_synonym_is_not_alias(self):
        rows,fx=examples()
        fx[0]["home"]="Manchester Utd"
        rows[0]["home_team"]="Manchester City"
        result,_=verified_rows(rows,fx,NOW)
        self.assertEqual(len(result),11)
    def test_known_alias_wrong_league_rejected(self):
        rows,fx=examples()
        fx[0]["home"]="Manchester Utd"
        rows[0]["home_team"]="Manchester United"
        rows[0]["league_short"]="It1"
        result,_=verified_rows(rows,fx,NOW)
        self.assertEqual(len(result),11)
    def test_known_alias_wrong_kickoff_rejected(self):
        rows,fx=examples()
        fx[0]["home"]="Manchester Utd"
        rows[0]["home_team"]="Manchester United"
        rows[0]["kickoff_text"]="10/11/2026 10:10 PM"
        result,_=verified_rows(rows,fx,NOW)
        self.assertEqual(len(result),11)

    def test_source_displayed_clock_offset_requires_multileague_corroboration(self):
        rows,fx=examples()
        # Reconstruct a coherent Forebet +8 display clock; the original UTC
        # parser rejected all 12. This is verified by independent fixture IDs.
        for row,t in zip(rows,fx):
            clock=t["kickoff"]+timedelta(hours=8)
            row["kickoff_text"]=clock.strftime("%m/%d/%Y %I:%M %p")
            row["match_date"]=clock.date().isoformat()
        output,info=verified_rows(rows,fx,NOW)
        self.assertEqual(len(output),12)
        self.assertEqual(info["clock_offset_minutes"],480)
        self.assertTrue(all(x["source_display_offset_minutes"]==480 for x in output))
        self.assertTrue(all(x["source_event_time"]==t["kickoff"].isoformat()
                            for x,t in zip(output,fx)))
    def test_two_conflicting_clock_offsets_never_publish(self):
        rows,fx=examples()
        for i in range(6):
            t=fx[i]["kickoff"]+timedelta(hours=1)
            rows[i]["kickoff_text"]=t.strftime("%m/%d/%Y %I:%M %p")
        models,info=verified_rows(rows,fx,NOW)
        self.assertEqual(models,[])
        self.assertEqual(info["reason"],"COHORT_TIME_NOT_CORROBORATED")

    def test_api_recovery_requires_individual_exact_identity(self):
        rows,fx=examples()
        ms=[{"id":t["match_id"],"kickoff":t["kickoff"].isoformat(),
             "home":t["home"],"away":t["away"],"league":t["league"],
             "sourceContext":{"identityStatus":"EXACT_CANONICAL_PROVIDER_FIXTURE"}} for t in fx]
        # Use FS IDs with an actual provider-event-shaped identifier.
        for i,m in enumerate(ms):
            m["id"]=f"FS:example{i:02d}"
        d={"generatedAt":NOW.isoformat(),"matches":ms,
           "source":"supabase-lightweight-enrichment-recovery",
           "recoveryMode":"LIGHTWEIGHT_CANONICAL_EVIDENCE"}
        self.assertEqual(len(canonical_feed_matches(d,NOW)),12)
        d["matches"][0]["sourceContext"]["identityStatus"]="SOURCE_NAME_ONLY"
        self.assertEqual(len(canonical_feed_matches(d,NOW)),11)
        d["source"]="flashscore-direct"
        with self.assertRaisesRegex(ValueError,"canonical authority"):
            canonical_feed_matches(d,NOW)
        d["source"]="supabase-lightweight-enrichment-recovery"
        d["recoveryMode"]="UNVERIFIED"
        with self.assertRaisesRegex(ValueError,"recovery mode"):
            canonical_feed_matches(d,NOW)

    def test_api_recovery_rejects_stale_generated_at_and_unverified_rows(self):
        ms=[{"id":f"FS:example{i:02d}","sourceContext":{
             "identityStatus":"EXACT_CANONICAL_PROVIDER_FIXTURE"}} for i in range(12)]
        d={"source":"flashscore-single-rpc-canonical",
           "generatedAt":(NOW-timedelta(hours=2)).isoformat(),"matches":ms}
        with self.assertRaisesRegex(ValueError,"stale"):
            canonical_feed_matches(d,NOW)
        d["generatedAt"]=NOW.isoformat()
        for m in ms: m["sourceContext"]["identityStatus"]="UNVERIFIED"
        with self.assertRaisesRegex(ValueError,"insufficient individually verified"):
            canonical_feed_matches(d,NOW)

    def test_source_league_allowlist(self):
        self.assertTrue(league_ok("EPL","EPL"))
        self.assertTrue(league_ok("Es1","LaLigaSPAIN: Standings"))
        self.assertFalse(league_ok("Es1","BundesligaGERMANY: Standings"))
        self.assertFalse(league_ok("Es5","LaLigaSPAIN: Standings"))

if __name__=="__main__":unittest.main()
