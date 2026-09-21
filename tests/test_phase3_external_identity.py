import unittest
from phase3.external_identity import choose_candidate, ranked_candidates

HK={"home_en":"Manchester United","away_en":"Arsenal","kickoff_hkt":"2026-09-21T19:00:00+08:00"}

def row(mid="1",home="Manchester United",away="Arsenal",kickoff="2026-09-21T11:00:00+00:00"):
    return {"id":mid,"home":home,"away":away,"kickoff":kickoff,"competition":"Premier League"}

class ExternalIdentityTests(unittest.TestCase):
    def test_exact_fixture_is_candidate(self):
        c,reason=choose_candidate(HK,[row()])
        self.assertEqual(reason,"CANDIDATE")
        self.assertEqual(c.source_match_id,"1")
        self.assertGreaterEqual(c.confidence,.85)

    def test_women_suffix_matches_external_w_format(self):
        hk={"home_en":"Vietnam Women","away_en":"Thailand Women","kickoff_hkt":"2026-09-21T18:30:00+08:00"}
        c,reason=choose_candidate(hk,[row("9","Vietnam W","Thailand W","2026-09-21T10:30:00+00:00")])
        self.assertEqual(reason,"CANDIDATE")
        self.assertEqual(c.source_match_id,"9")
        self.assertEqual(c.confidence,1.0)

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

    def test_ranked_diagnostics_expose_components_without_promoting_weak_match(self):
        weak=row("7",home="Manchester Utd Youth",away="Arsenal Academy")
        ranked=ranked_candidates(HK,[weak])
        self.assertEqual(len(ranked),1)
        self.assertEqual(ranked[0].source_match_id,"7")
        self.assertGreater(ranked[0].home_score,0)
        c,reason=choose_candidate(HK,[weak])
        self.assertIsNone(c)
        self.assertEqual(reason,"NO_HIGH_CONFIDENCE_CANDIDATE")

if __name__=="__main__": unittest.main()
