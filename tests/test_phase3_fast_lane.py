import unittest
from phase3.fast_lane import join_verified_fast_rows, normalize_fotmob_board


class FastLaneTests(unittest.TestCase):
    def test_one_board_payload_normalizes_multiple_matches(self):
        payload={"matches":[
            {"id":11,"status":{"liveTime":{"short":"23"},"scoreStr":"1 - 0","reason":{"short":"1st"}}},
            {"id":12,"status":{"liveTime":{"short":"67"},"scoreStr":"2 - 2","reason":{"short":"2nd"}}},
        ]}
        rows=normalize_fotmob_board(payload,"2026-09-22T01:00:00+00:00")
        self.assertEqual(len(rows),2); self.assertEqual(rows[1]["minute"],67); self.assertEqual(rows[1]["away_score"],2)

    def test_real_data_matches_shape_uses_leagues_and_team_scores(self):
        payload={"leagues":[{"matches":[{
            "id":5190727,
            "home":{"name":"Home","score":2},
            "away":{"name":"Away","score":1},
            "status":{"liveTime":{"short":"67'"},"reason":{"short":"2nd"}}
        }]}]}
        rows=normalize_fotmob_board(payload,"2026-09-22T03:00:00+00:00")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["external_id"],"5190727")
        self.assertEqual(rows[0]["minute"],67)
        self.assertEqual((rows[0]["home_score"],rows[0]["away_score"]),(2,1))

    def test_malformed_unrelated_containers_do_not_kill_board(self):
        payload={"leagues":[None,"bad",{"matches":None},{"matches":[None,{"id":11,"home":"bad","away":None,"status":"bad"}]}]}
        rows=normalize_fotmob_board(payload,"2026-09-22T03:00:00+00:00")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["external_id"],"11")
        self.assertIsNone(rows[0]["home_score"])

    def test_only_verified_identity_can_join(self):
        registry=[
            {"hkjc_event_id":"FB1","source":"FOTMOB","external_id":"11","status":"VERIFIED"},
            {"hkjc_event_id":"FB2","source":"FOTMOB","external_id":"12","status":"CANDIDATE"},
        ]
        board=[
            {"source":"FOTMOB","external_id":"11","status":"1st","minute":23,"home_score":1,"away_score":0,"observed_at":"t"},
            {"source":"FOTMOB","external_id":"12","status":"2nd","minute":67,"home_score":2,"away_score":2,"observed_at":"t"},
        ]
        joined,unmapped=join_verified_fast_rows(registry,board)
        self.assertEqual([r["hkjc_event_id"] for r in joined],["FB1"])
        self.assertEqual([r["external_id"] for r in unmapped],["12"])

    def test_registry_source_match_id_is_accepted(self):
        registry=[{"hkjc_event_id":"FB1","source":"FOTMOB","source_match_id":"11","status":"VERIFIED"}]
        board=[{"source":"FOTMOB","external_id":"11","status":"1st","minute":23,"home_score":1,"away_score":0,"observed_at":"t"}]
        joined,_=join_verified_fast_rows(registry,board)
        self.assertEqual(joined[0]["hkjc_event_id"],"FB1")

    def test_no_fuzzy_rematch_when_external_id_missing(self):
        registry=[{"hkjc_event_id":"FB1","source":"FOTMOB","external_id":"11","status":"VERIFIED"}]
        board=[{"source":"FOTMOB","external_id":"999","status":"1st","minute":5,"home_score":0,"away_score":0,"observed_at":"t"}]
        joined,unmapped=join_verified_fast_rows(registry,board)
        self.assertEqual(joined,[]); self.assertEqual(len(unmapped),1)

if __name__=="__main__": unittest.main()
