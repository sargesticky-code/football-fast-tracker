import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from scripts.phase3_collect_fotmob_identity import eligible_rows


class Layer2AuthorityGateTests(unittest.TestCase):
    def payload(self, status="FIRSTHALF", selling="SELLINGSTARTED"):
        return {
            "fetched_at": "2026-09-21T14:00:00+00:00",
            "rows": [{
                "hkjc_event_id": "FB1",
                "match_id": "5001",
                "status": status,
                "pool_status": selling,
                "home_en": "Home",
                "away_en": "Away",
            }],
        }

    @patch("scripts.phase3_collect_fotmob_identity.datetime")
    def test_halftime_completed_never_reaches_external_collector(self, dt):
        dt.now.return_value = datetime(2026,9,21,14,0,1,tzinfo=timezone.utc)
        dt.side_effect = lambda *a, **k: datetime(*a, **k)
        rows,health,_=eligible_rows(self.payload(status="FIRSTHALFCOMPLETED"))
        self.assertEqual(rows, [])
        self.assertEqual(health, "FRESH_NO_LIVE_ROWS")

    @patch("scripts.phase3_collect_fotmob_identity.datetime")
    def test_selling_started_live_row_is_forwarded(self, dt):
        dt.now.return_value = datetime(2026,9,21,14,0,1,tzinfo=timezone.utc)
        rows,health,_=eligible_rows(self.payload())
        self.assertEqual(len(rows), 1)
        self.assertEqual(health, "FRESH_ELIGIBLE")

    @patch("scripts.phase3_collect_fotmob_identity.datetime")
    def test_stale_authority_never_reaches_external_collector(self, dt):
        dt.now.return_value = datetime(2026,9,21,14,10,0,tzinfo=timezone.utc)
        rows,health,_=eligible_rows(self.payload())
        self.assertEqual(rows, [])
        self.assertEqual(health, "STALE_AUTHORITY")


if __name__ == "__main__":
    unittest.main()
