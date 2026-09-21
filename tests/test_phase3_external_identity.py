import unittest
from phase3.external_identity import choose_candidate

HK={"home_en":"Manchester United","away_en":"Arsenal","kickoff_hkt":"2026-09-21T19:00:00+08:00"}

def row(mid="1",home="Manchester United",away="Arsenal",kickoff="2026-09-21T11:00:00+00:00"):
    return {"id":mid,"home":home,"away":away,"kickoff":kickoff,"competition":"Premier League"}

class ExternalIdentityTests(unittest.TestCase):
    def test_exact_fixture_is_candidate(self):
        c,reason=choose_candidate(HK,[row()])
        self.assertEqual(reason,"CANDIDATE")
        self.assertEqual(c.source_match_id,"1")
        self.assertGreaterEqual(c.confidence,.85)

    def test_reversed_fixture_fails_closed(self):
        c,reason=choose_candidate(HK,[row(home="Arsenal",away="Manchester United")])
        self.assertIsNone(c)
        self.assertEqual(reason,"NO_HIGH_CONFIDENCE_CANDIDATE")

    def test_large_kickoff_drift_fails_closed(self):
        c,reason=choose_candidate(HK,[row(kickoff="2026-09-21T13:00:00+00:00")])
        self.assertIsNone(c)

    def test_weak_names_fail_closed(self):
        c,reason=choose_candidate(HK,[row(home="United City",away="Arsenal Youth")])
        self.assertIsNone(c)

    def test_close_two_candidates_are_ambiguous(self):
        c,reason=choose_candidate(HK,[row("1"),row("2",kickoff="2026-09-21T11:01:00+00:00")])
        self.assertIsNone(c)
        self.assertEqual(reason,"AMBIGUOUS_CANDIDATES")

if __name__=="__main__": unittest.main()
