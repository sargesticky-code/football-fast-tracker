import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from capture_forebet_canonical_light import verified_rows,displayed_utc,league_ok

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

    def test_source_league_allowlist(self):
        self.assertTrue(league_ok("EPL","EPL"))
        self.assertTrue(league_ok("Es1","LaLigaSPAIN: Standings"))
        self.assertFalse(league_ok("Es1","BundesligaGERMANY: Standings"))
        self.assertFalse(league_ok("Es5","LaLigaSPAIN: Standings"))

if __name__=="__main__":unittest.main()
