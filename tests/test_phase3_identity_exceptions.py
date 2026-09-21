import unittest
from phase3.identity_exceptions import upsert_exception, prune_exceptions


class IdentityExceptionTests(unittest.TestCase):
    def test_repeated_unresolved_observation_updates_same_event(self):
        rows=upsert_exception([],{
            "hkjc_event_id":"FB1","home":"A","away":"B","reason":"SOURCE_COVERAGE_GAP",
            "providers_tried":["FOTMOB","ESPN"],"observed_at":"2026-09-21T10:00:00+00:00",
        })
        rows=upsert_exception(rows,{
            "hkjc_event_id":"FB1","home":"A","away":"B","reason":"SOURCE_COVERAGE_GAP",
            "providers_tried":["FOTMOB","ESPN"],"observed_at":"2026-09-21T10:05:00+00:00",
        })
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["observations"],2)
        self.assertEqual(rows[0]["first_seen_at"],"2026-09-21T10:00:00+00:00")
        self.assertEqual(rows[0]["last_seen_at"],"2026-09-21T10:05:00+00:00")

    def test_missing_event_never_creates_exception(self):
        self.assertEqual(upsert_exception([], {"reason":"HKJC_NAME_GAP"}),[])

    def test_prune_keeps_only_active_or_explicit_terminal(self):
        rows=[{"hkjc_event_id":"ACTIVE"},{"hkjc_event_id":"DONE"},{"hkjc_event_id":"OLD"}]
        kept=prune_exceptions(rows,{"ACTIVE"},{"DONE"})
        self.assertEqual({x["hkjc_event_id"] for x in kept},{"ACTIVE","DONE"})

if __name__=="__main__": unittest.main()
