import unittest
from datetime import datetime,timezone
from scripts.fotmob_h2h_worker import build

class Fake:
    def matches(self,date):
        return {"leagues":[{"name":"Test","matches":[{
            "id":321,"timeTS":int(datetime(2026,9,24,19,0,tzinfo=timezone.utc).timestamp()*1000),
            "home":{"id":10,"name":"Home Club"},"away":{"id":20,"name":"Away Club"},"status":{}
        }]}]}
    def match_details(self,match_id):
        return {"content":{"h2h":{"matches":[{
            "matchUrl":"/livescores/99/matchfacts/x","home":{"id":"20","name":"Away Club"},"away":{"id":"10","name":"Home Club"},
            "status":{"finished":True,"scoreStr":"1 - 2","startDateStr":"Jan 1, 2026"},"league":{"name":"Test"}
        }]}}}

class FotMobWorkerTests(unittest.TestCase):
    def row(self):
        return {"hkjc_event_id":"FB1","kickoff_hkt":"2026-09-25T03:00:00+08:00","home_id":"H1","away_id":"A1","home":"Home Club","away":"Away Club","tournament":"TST"}
    def test_worker_produces_verified_h2h(self):
        out=build([self.row()],[],Fake(),10)
        self.assertEqual(out[0]["mapping_status"],"VERIFIED"); self.assertEqual(out[0]["quality"],"H2H_OK")
        self.assertEqual(out[0]["last5"],"H")
    def test_source_failure_is_nonfatal(self):
        class Broken(Fake):
            def matches(self,date): raise RuntimeError("down")
        out=build([self.row()],[],Broken(),10)
        self.assertEqual(out[0]["quality"],"SOURCE_UNAVAILABLE")
    def test_previous_h2h_is_reused_without_detail_call(self):
        class Counting(Fake):
            def __init__(self): self.details=0
            def match_details(self,match_id):
                self.details+=1
                return super().match_details(match_id)
        client=Counting()
        previous=[{
            **self.row(),
            "fotmob_match_id":"321","mapping_status":"VERIFIED","mapping_reason":"exact_pair_and_kickoff",
            "quality":"H2H_OK","h2h_games":"2","home_wins":"1","draws":"1","away_wins":"0",
            "home_goals":"3","away_goals":"1","avg_total_goals":"2.00","last5":"HD",
            "meetings_json":'[{"result":"H"},{"result":"D"}]'
        }]
        out=build([self.row()],[],client,10,previous_rows=previous)
        self.assertEqual(out[0]["quality"],"H2H_OK")
        self.assertEqual(out[0]["last5"],"HD")
        self.assertEqual(client.details,0)

    def test_budget_is_deferred(self):
        out=build([self.row()],[],Fake(),0)
        self.assertEqual(out[0]["quality"],"DEFERRED_BUDGET")

if __name__=="__main__": unittest.main()
