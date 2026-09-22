import unittest
from phase3.fast_lane import fast_lane_health, join_verified_fast_rows, normalize_fotmob_board


class FastLaneTests(unittest.TestCase):
    def test_one_board_payload_normalizes_multiple_matches(self):
        payload={"matches":[{"id":11,"status":{"liveTime":{"short":"23"},"scoreStr":"1 - 0","reason":{"short":"1st"}}},{"id":12,"status":{"liveTime":{"short":"67"},"scoreStr":"2 - 2","reason":{"short":"2nd"}}}]}
        rows=normalize_fotmob_board(payload,"2026-09-22T01:00:00+00:00")
        self.assertEqual(len(rows),2); self.assertEqual(rows[1]["minute"],67); self.assertEqual(rows[1]["away_score"],2)

    def test_real_data_matches_shape_uses_leagues_and_team_scores(self):
        payload={"leagues":[{"matches":[{"id":5190727,"home":{"name":"Home","score":2},"away":{"name":"Away","score":1},"status":{"liveTime":{"short":"67'"},"reason":{"short":"2nd"}}}]}]}
        rows=normalize_fotmob_board(payload,"2026-09-22T03:00:00+00:00")
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]["external_id"],"5190727"); self.assertEqual(rows[0]["minute"],67); self.assertEqual((rows[0]["home_score"],rows[0]["away_score"]),(2,1))

    def test_stoppage_time_keeps_base_minute_without_fabrication(self):
        payload={"matches":[{"id":13,"home":{"score":1},"away":{"score":1},"status":{"liveTime":{"short":"90 + 4'"},"reason":{"short":"2nd"}}}]}
        row=normalize_fotmob_board(payload,"2026-09-22T03:00:00+00:00")[0]
        self.assertEqual(row["minute"],90); self.assertEqual(row["status"],"2nd")

    def test_halftime_status_is_preserved_without_inventing_minute(self):
        payload={"matches":[{"id":14,"home":{"score":0},"away":{"score":0},"status":{"reason":{"short":"HT"}}}]}
        row=normalize_fotmob_board(payload,"2026-09-22T03:00:00+00:00")[0]
        self.assertEqual(row["status"],"HT"); self.assertIsNone(row["minute"])

    def test_malformed_unrelated_containers_do_not_kill_board(self):
        payload={"leagues":[None,"bad",{"matches":None},{"matches":[None,{"id":11,"home":"bad","away":None,"status":"bad"}]}]}
        rows=normalize_fotmob_board(payload,"2026-09-22T03:00:00+00:00")
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]["external_id"],"11"); self.assertIsNone(rows[0]["home_score"])

    def test_only_verified_identity_can_join(self):
        registry=[{"hkjc_event_id":"FB1","source":"FOTMOB","external_id":"11","status":"VERIFIED"},{"hkjc_event_id":"FB2","source":"FOTMOB","external_id":"12","status":"CANDIDATE"}]
        board=[{"source":"FOTMOB","external_id":"11","status":"1st","minute":23,"home_score":1,"away_score":0,"observed_at":"t"},{"source":"FOTMOB","external_id":"12","status":"2nd","minute":67,"home_score":2,"away_score":2,"observed_at":"t"}]
        joined,unmapped=join_verified_fast_rows(registry,board)
        self.assertEqual([r["hkjc_event_id"] for r in joined],["FB1"]); self.assertEqual([r["external_id"] for r in unmapped],["12"])

    def test_registry_source_match_id_is_accepted(self):
        registry=[{"hkjc_event_id":"FB1","source":"FOTMOB","source_match_id":"11","status":"VERIFIED"}]
        board=[{"source":"FOTMOB","external_id":"11","status":"1st","minute":23,"home_score":1,"away_score":0,"observed_at":"t"}]
        joined,_=join_verified_fast_rows(registry,board); self.assertEqual(joined[0]["hkjc_event_id"],"FB1")

    def test_no_fuzzy_rematch_when_external_id_missing(self):
        registry=[{"hkjc_event_id":"FB1","source":"FOTMOB","external_id":"11","status":"VERIFIED"}]
        board=[{"source":"FOTMOB","external_id":"999","status":"1st","minute":5,"home_score":0,"away_score":0,"observed_at":"t"}]
        joined,unmapped=join_verified_fast_rows(registry,board); self.assertEqual(joined,[]); self.assertEqual(len(unmapped),1)

    def test_fast_health_distinguishes_live_terminal_and_stale(self):
        now="2026-09-22T09:00:10+00:00"; live=[{"status":"2nd","minute":67,"home_score":2,"away_score":1}]; terminal=[{"status":"FT","minute":90,"home_score":2,"away_score":1}]
        self.assertEqual(fast_lane_health(live,"2026-09-22T09:00:08+00:00",now=now)["health"],"FRESH_LIVE")
        self.assertEqual(fast_lane_health(terminal,"2026-09-22T09:00:08+00:00",now=now)["health"],"FRESH_PARTIAL_OR_TERMINAL")
        self.assertEqual(fast_lane_health(live,"2026-09-22T08:59:00+00:00",now=now)["health"],"STALE_FAST_SNAPSHOT")

    def test_status_only_rows_cannot_satisfy_live_minute_evidence(self):
        now="2026-09-22T09:00:10+00:00"
        for status in ("1st","2nd","HT","LIVE"):
            health=fast_lane_health([{"status":status,"minute":None,"home_score":0,"away_score":0}],"2026-09-22T09:00:09+00:00",now=now)
            self.assertEqual(health["health"],"FRESH_PARTIAL_OR_TERMINAL"); self.assertEqual(health["live_rows"],0)

    def test_missing_or_blank_status_cannot_satisfy_live_evidence(self):
        now="2026-09-22T09:00:10+00:00"
        for status in (None,"","   "):
            health=fast_lane_health([{"status":status,"minute":67,"home_score":1,"away_score":0}],"2026-09-22T09:00:09+00:00",now=now)
            self.assertEqual(health["health"],"FRESH_PARTIAL_OR_TERMINAL"); self.assertEqual(health["live_rows"],0)

    def test_live_minute_without_complete_score_cannot_satisfy_exit_evidence(self):
        now="2026-09-22T09:00:10+00:00"
        for row in ({"status":"2nd","minute":67,"home_score":None,"away_score":1},{"status":"2nd","minute":67,"home_score":2,"away_score":None}):
            health=fast_lane_health([row],"2026-09-22T09:00:09+00:00",now=now)
            self.assertEqual(health["health"],"FRESH_PARTIAL_OR_TERMINAL"); self.assertEqual(health["live_rows"],0)

    def test_impossible_minute_or_score_values_fail_closed(self):
        now="2026-09-22T09:00:10+00:00"
        bad_rows=[{"status":"1st","minute":0,"home_score":0,"away_score":0},{"status":"2nd","minute":131,"home_score":1,"away_score":0},{"status":"2nd","minute":67,"home_score":-1,"away_score":0},{"status":"2nd","minute":67,"home_score":1,"away_score":-1}]
        for row in bad_rows:
            health=fast_lane_health([row],"2026-09-22T09:00:09+00:00",now=now)
            self.assertEqual(health["health"],"FRESH_PARTIAL_OR_TERMINAL"); self.assertEqual(health["live_rows"],0)

    def test_fast_health_fails_closed_on_request_failure_or_bad_clock(self):
        now="2026-09-22T09:00:10+00:00"; row=[{"status":"1st","minute":12,"home_score":0,"away_score":0}]
        self.assertEqual(fast_lane_health(row,"2026-09-22T09:00:09+00:00",now=now,request_failures=1)["health"],"REQUEST_FAILED")
        self.assertEqual(fast_lane_health(row,"not-a-time",now=now)["health"],"NO_FAST_SNAPSHOT")
        self.assertEqual(fast_lane_health(row,"2026-09-22T09:01:00+00:00",now=now)["health"],"NO_FAST_SNAPSHOT")

if __name__=="__main__": unittest.main()
