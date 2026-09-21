import unittest
from phase3.sofascore_identity import normalize_board

class SofascoreIdentityTests(unittest.TestCase):
    def test_normalizes_scheduled_event_without_creating_authority(self):
        rows=normalize_board({"events":[{
            "id":123,
            "startTimestamp":1789992000,
            "homeTeam":{"name":"Werder Bremen Women"},
            "awayTeam":{"name":"Stuttgart Women"},
            "tournament":{"name":"Frauen-Bundesliga"},
        }]})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["id"],123)
        self.assertEqual(rows[0]["home"],"Werder Bremen Women")
        self.assertEqual(rows[0]["away"],"Stuttgart Women")
        self.assertIn("+00:00",rows[0]["kickoff"])
        self.assertNotIn("eligible",rows[0])

    def test_missing_events_is_empty(self):
        self.assertEqual(normalize_board({}),[])

if __name__=="__main__": unittest.main()
