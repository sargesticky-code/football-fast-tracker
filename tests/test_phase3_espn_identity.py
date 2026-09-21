import unittest
from phase3.espn_identity import normalize_board


class EspnIdentityTests(unittest.TestCase):
    def test_normalizes_home_away_without_authority(self):
        rows=normalize_board({"events":[{
            "id":"401",
            "date":"2026-09-21T18:30:00Z",
            "league":{"name":"Frauen-Bundesliga"},
            "competitions":[{"competitors":[
                {"homeAway":"away","team":{"displayName":"Stuttgart Women"}},
                {"homeAway":"home","team":{"displayName":"Werder Bremen Women"}},
            ]}]
        }]})
        self.assertEqual(rows[0]["id"],"401")
        self.assertEqual(rows[0]["home"],"Werder Bremen Women")
        self.assertEqual(rows[0]["away"],"Stuttgart Women")
        self.assertNotIn("eligible",rows[0])

    def test_incomplete_event_fails_closed(self):
        self.assertEqual(normalize_board({"events":[{"id":"1","competitions":[]}]}),[])


if __name__=="__main__": unittest.main()
