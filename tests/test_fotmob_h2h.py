import unittest
from datetime import datetime,timezone
from scripts.fotmob_h2h import Fixture,match_fixture,normalize_h2h,summarize

class FotMobH2HTests(unittest.TestCase):
    def test_board_mapping_with_verified_alias(self):
        f=Fixture("FB1",datetime(2026,9,24,19,0,tzinfo=timezone.utc),"D R Congo","Ghana")
        board={"leagues":[{"name":"Test","matches":[{
            "id":101,"timeTS":int(datetime(2026,9,24,19,5,tzinfo=timezone.utc).timestamp()*1000),
            "home":{"id":1,"name":"DR Congo"},"away":{"id":2,"name":"Ghana"},"status":{}
        }]}]}
        m=match_fixture(f,[board],aliases={"D R Congo":["DR Congo"]})
        self.assertEqual(m.status,"VERIFIED"); self.assertEqual(m.match_id,101)

    def test_cohort_not_collapsed(self):
        f=Fixture("FB2",datetime(2026,9,24,19,0,tzinfo=timezone.utc),"Arsenal Women","Chelsea Women")
        board={"leagues":[{"matches":[{
            "id":102,"timeTS":int(datetime(2026,9,24,19,0,tzinfo=timezone.utc).timestamp()*1000),
            "home":{"id":3,"name":"Arsenal"},"away":{"id":4,"name":"Chelsea"},"status":{}
        }]}]}
        self.assertEqual(match_fixture(f,[board]).status,"UNMAPPED")

    def test_direct_h2h_reorients_scores(self):
        payload={"content":{"h2h":{"summary":[1,1,1],"matches":[
            {"matchUrl":"/livescores/11/matchfacts/x","home":{"id":"2","name":"Away"},"away":{"id":"1","name":"Home"},
             "status":{"finished":True,"scoreStr":"3 - 1","startDateStr":"Jan 1, 2026"},"league":{"name":"League"}},
            {"matchUrl":"/livescores/12/matchfacts/x","home":{"id":"1","name":"Home"},"away":{"id":"2","name":"Away"},
             "status":{"finished":True,"scoreStr":"2 - 0","startDateStr":"Jan 1, 2025"},"league":{"name":"League"}},
            {"matchUrl":"/livescores/13/matchfacts/x","home":{"id":"1","name":"Home"},"away":{"id":"2","name":"Away"},
             "status":{"finished":False},"league":{"name":"League"}}
        ]}}}
        meetings=normalize_h2h(payload,current_home_team_id=1,current_away_team_id=2)
        self.assertEqual([x["result"] for x in meetings],["A","H"])
        s=summarize(meetings); self.assertEqual(s["h2h_games"],2); self.assertEqual(s["last5"],"AH")

    def test_no_history_is_not_failure(self):
        s=summarize([]); self.assertEqual(s["quality"],"NO_HISTORY")

if __name__=="__main__": unittest.main()
