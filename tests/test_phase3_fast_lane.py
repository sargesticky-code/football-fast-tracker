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

    def test_no_fuzzy_rematch_when_external_id_missing(self):
        registry=[{"hkjc_event_id":"FB1","source":"FOTMOB","external_id":"11","status":"VERIFIED"}]
        board=[{"source":"FOTMOB","external_id":"999","status":"1st","minute":5,"home_score":0,"away_score":0,"observed_at":"t"}]
        joined,unmapped=join_verified_fast_rows(registry,board)
        self.assertEqual(joined,[]); self.assertEqual(len(unmapped),1)

if __name__=="__main__": unittest.main()
