import unittest
from phase3.state_continuity import registry_fingerprint, assert_empty_cycle_retention


def row(status="CANDIDATE", count=1, span=0.0, mid="A"):
    return {"hkjc_event_id":"FB1","source":"FOTMOB","source_match_id":mid,
            "status":status,"evidence_count":count,"evidence_span_seconds":span}


class StateContinuityTests(unittest.TestCase):
    def test_candidate_survives_empty_cycle(self):
        before=registry_fingerprint([row(count=2,span=60)])
        after=registry_fingerprint([row(count=2,span=60)])
        assert_empty_cycle_retention(before,after)

    def test_candidate_may_promote(self):
        before=registry_fingerprint([row(count=2,span=60)])
        after=registry_fingerprint([row(status="VERIFIED",count=3,span=180)])
        assert_empty_cycle_retention(before,after)

    def test_candidate_disappearance_fails(self):
        before=registry_fingerprint([row(count=2,span=60)])
        with self.assertRaisesRegex(AssertionError,"candidate identity disappeared"):
            assert_empty_cycle_retention(before,registry_fingerprint([]))

    def test_candidate_evidence_cannot_regress(self):
        before=registry_fingerprint([row(count=2,span=60)])
        after=registry_fingerprint([row(count=1,span=0)])
        with self.assertRaisesRegex(AssertionError,"candidate evidence regressed"):
            assert_empty_cycle_retention(before,after)

    def test_verified_disappearance_fails(self):
        before=registry_fingerprint([row(status="VERIFIED",count=3,span=180)])
        with self.assertRaisesRegex(AssertionError,"verified identity disappeared"):
            assert_empty_cycle_retention(before,registry_fingerprint([]))

if __name__=="__main__": unittest.main()
