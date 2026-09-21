import unittest
from phase3.identity_registry import IdentityObservation, rebuild_registry, usable_mapping, merge_terminal_registry

def o(event="FB1", mid="A", conf=.90, t="2026-09-21T01:00:00+00:00", home="H", away="A", ko="2026-09-21T02:00:00+00:00"):
    return IdentityObservation(event,"FOTMOB",mid,conf,t,home,away,ko,"L")

class IdentityRegistryTests(unittest.TestCase):
    def test_one_observation_stays_candidate(self):
        r=rebuild_registry([o()]); self.assertEqual(r[0]["status"],"CANDIDATE"); self.assertIsNone(usable_mapping(r,"FB1","FOTMOB"))

    def test_three_consistent_observations_promote(self):
        r=rebuild_registry([o(t=f"2026-09-21T01:0{i}:00+00:00") for i in range(3)])
        self.assertEqual(r[0]["status"],"VERIFIED"); self.assertTrue(r[0]["terminal"]); self.assertEqual(r[0]["evidence_count"],3)

    def test_three_near_simultaneous_observations_do_not_promote(self):
        evidence=[
            o(t="2026-09-21T01:00:00+00:00"),
            o(t="2026-09-21T01:00:10+00:00"),
            o(t="2026-09-21T01:00:20+00:00"),
        ]
        r=rebuild_registry(evidence)
        self.assertEqual(r[0]["status"],"CANDIDATE")
        self.assertEqual(r[0]["evidence_count"],3)
        self.assertEqual(r[0]["evidence_span_seconds"],20.0)

    def test_exact_retry_does_not_inflate_evidence_count(self):
        same=o(t="2026-09-21T01:00:00+00:00")
        r=rebuild_registry([same,same,same])
        self.assertEqual(r[0]["status"],"CANDIDATE")
        self.assertEqual(r[0]["evidence_count"],1)

    def test_retry_plus_two_real_observations_promotes(self):
        first=o(t="2026-09-21T01:00:00+00:00")
        r=rebuild_registry([first,first,o(t="2026-09-21T01:05:00+00:00"),o(t="2026-09-21T01:10:00+00:00")])
        self.assertEqual(r[0]["status"],"VERIFIED")
        self.assertEqual(r[0]["evidence_count"],3)

    def test_low_confidence_does_not_promote(self):
        r=rebuild_registry([o(conf=.80,t=f"2026-09-21T01:0{i}:00+00:00") for i in range(3)]); self.assertEqual(r[0]["status"],"CANDIDATE")

    def test_competing_external_ids_fail_closed(self):
        evidence=[o(mid="A",t=f"2026-09-21T01:0{i}:00+00:00") for i in range(3)]+[o(mid="B",t="2026-09-21T01:10:00+00:00")]
        r=rebuild_registry(evidence); self.assertTrue(all(x["status"]=="CONFLICT" for x in r)); self.assertIsNone(usable_mapping(r,"FB1","FOTMOB"))

    def test_same_external_id_cannot_own_two_hkjc_events(self):
        r=rebuild_registry([o(event="FB1"),o(event="FB2",t="2026-09-21T01:01:00+00:00")]); self.assertTrue(all(x["status"]=="CONFLICT" for x in r))

    def test_fixture_drift_fails_closed(self):
        r=rebuild_registry([o(t="2026-09-21T01:00:00+00:00"),o(t="2026-09-21T01:01:00+00:00"),o(t="2026-09-21T01:02:00+00:00",ko="2026-09-22T02:00:00+00:00")]); self.assertEqual(r[0]["status"],"CONFLICT")

    def test_verified_mapping_survives_empty_cycle(self):
        prior=rebuild_registry([o(t=f"2026-09-21T01:0{i}:00+00:00") for i in range(3)])
        merged=merge_terminal_registry(prior,[]); self.assertEqual(merged[0]["status"],"VERIFIED"); self.assertEqual(merged[0]["source_match_id"],"A")

    def test_verified_mapping_is_never_silently_replaced(self):
        prior=rebuild_registry([o(t=f"2026-09-21T01:0{i}:00+00:00") for i in range(3)])
        proposed=rebuild_registry([o(mid="B",t="2026-09-21T02:00:00+00:00")])
        merged=merge_terminal_registry(prior,proposed)
        self.assertEqual(merged[0]["status"],"LOCKED_CONFLICT"); self.assertEqual(merged[0]["source_match_id"],"A"); self.assertEqual(merged[0]["quarantined_ids"],["B"]); self.assertIsNone(usable_mapping(merged,"FB1","FOTMOB"))

if __name__=="__main__": unittest.main()
