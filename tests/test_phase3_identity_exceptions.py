import unittest
from phase3.identity_exceptions import upsert_exception, prune_exceptions, resolve_verified_exceptions


class IdentityExceptionTests(unittest.TestCase):
    def test_repeated_unresolved_observation_updates_same_event(self):
        rows=upsert_exception([],{"hkjc_event_id":"FB1","home":"A","away":"B","reason":"SOURCE_COVERAGE_GAP","providers_tried":["FOTMOB","ESPN"],"observed_at":"2026-09-21T10:00:00+00:00"})
        rows=upsert_exception(rows,{"hkjc_event_id":"FB1","home":"A","away":"B","reason":"SOURCE_COVERAGE_GAP","providers_tried":["FOTMOB","ESPN"],"observed_at":"2026-09-21T10:05:00+00:00"})
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]["observations"],2)
        self.assertEqual(rows[0]["first_seen_at"],"2026-09-21T10:00:00+00:00"); self.assertEqual(rows[0]["last_seen_at"],"2026-09-21T10:05:00+00:00")
        self.assertEqual(rows[0]["status"],"ACTIVE")

    def test_verified_mapping_resolves_exception_with_terminal_identity(self):
        rows=upsert_exception([],{"hkjc_event_id":"FB1","reason":"SOURCE_COVERAGE_GAP","observed_at":"2026-09-21T10:00:00+00:00"})
        rows=resolve_verified_exceptions(rows,[{"hkjc_event_id":"FB1","status":"VERIFIED","source":"FOTMOB","source_match_id":"123"}],"2026-09-21T10:10:00+00:00")
        self.assertEqual(rows[0]["status"],"RESOLVED"); self.assertEqual(rows[0]["resolved_source"],"FOTMOB")
        self.assertEqual(rows[0]["resolved_source_match_id"],"123"); self.assertEqual(rows[0]["resolved_at"],"2026-09-21T10:10:00+00:00")

    def test_candidate_does_not_resolve_exception(self):
        rows=upsert_exception([],{"hkjc_event_id":"FB1","reason":"SOURCE_COVERAGE_GAP"})
        rows=resolve_verified_exceptions(rows,[{"hkjc_event_id":"FB1","status":"CANDIDATE","source":"ESPN","source_match_id":"9"}])
        self.assertEqual(rows[0]["status"],"ACTIVE"); self.assertNotIn("resolved_at",rows[0])

    def test_new_unresolved_observation_reopens_resolved_exception(self):
        rows=[{"hkjc_event_id":"FB1","status":"RESOLVED","observations":2,"resolved_at":"old","resolved_source":"FOTMOB","resolved_source_match_id":"123"}]
        rows=upsert_exception(rows,{"hkjc_event_id":"FB1","reason":"NAME_MISMATCH","observed_at":"2026-09-21T11:00:00+00:00"})
        self.assertEqual(rows[0]["status"],"ACTIVE"); self.assertEqual(rows[0]["observations"],3); self.assertNotIn("resolved_at",rows[0])

    def test_missing_event_never_creates_exception(self):
        self.assertEqual(upsert_exception([], {"reason":"HKJC_NAME_GAP"}),[])

    def test_prune_keeps_only_active_or_explicit_terminal(self):
        rows=[{"hkjc_event_id":"ACTIVE"},{"hkjc_event_id":"DONE"},{"hkjc_event_id":"OLD"}]
        kept=prune_exceptions(rows,{"ACTIVE"},{"DONE"})
        self.assertEqual({x["hkjc_event_id"] for x in kept},{"ACTIVE","DONE"})

if __name__=="__main__": unittest.main()
