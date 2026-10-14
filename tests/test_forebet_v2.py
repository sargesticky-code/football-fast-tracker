"""Offline Forebet V2 contract: no fake probability, wrong match or stale FS ID."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from forebet_v2 import verified_rows, canonical_from_oidc

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
