from datetime import datetime, timedelta, timezone
import unittest

from phase3.hkjc_authority import evaluate_authority


NOW = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)


def row(**overrides):
    base = {
        "hkjc_event_id": "FB5502",
        "match_id": "50000001",
        "status": "FIRSTHALF",
        "pool_status": "SELLINGSTARTED",
    }
    base.update(overrides)
    return base


class HkjcAuthorityTests(unittest.TestCase):
    def test_fresh_selling_live_row_is_eligible(self):
        result = evaluate_authority(
            [row()],
            source_fetched_at=NOW - timedelta(seconds=20),
            now=NOW,
        )
        self.assertEqual(result.health, "FRESH_ELIGIBLE")
        self.assertTrue(result.authority_usable)
        self.assertEqual(result.eligible_rows, 1)
        self.assertTrue(result.rows[0]["phase3_eligible"])

    def test_stale_snapshot_fails_closed(self):
        result = evaluate_authority(
            [row()],
            source_fetched_at=NOW - timedelta(seconds=301),
            now=NOW,
        )
        self.assertEqual(result.health, "STALE_AUTHORITY")
        self.assertFalse(result.authority_usable)
        self.assertEqual(result.eligible_rows, 0)
        self.assertEqual(result.rows[0]["phase3_authority_reason"], "STALE_AUTHORITY")

    def test_selling_stopped_is_not_eligible(self):
        result = evaluate_authority(
            [row(pool_status="SELLINGSTOPPED")],
            source_fetched_at=NOW,
            now=NOW,
        )
        self.assertEqual(result.health, "FRESH_NO_LIVE_ROWS")
        self.assertEqual(result.not_selling_rows, 1)
        self.assertFalse(result.rows[0]["phase3_eligible"])

    def test_halftime_completed_is_not_live(self):
        result = evaluate_authority(
            [row(status="FIRSTHALFCOMPLETED")],
            source_fetched_at=NOW,
            now=NOW,
        )
        self.assertEqual(result.not_live_rows, 1)
        self.assertFalse(result.rows[0]["phase3_eligible"])

    def test_missing_identity_fails_closed(self):
        result = evaluate_authority(
            [row(match_id="")],
            source_fetched_at=NOW,
            now=NOW,
        )
        self.assertEqual(result.health, "IDENTITY_GAP")
        self.assertFalse(result.authority_usable)
        self.assertEqual(result.identity_gap_rows, 1)

    def test_missing_snapshot_fails_closed(self):
        result = evaluate_authority([row()], source_fetched_at=None, now=NOW)
        self.assertEqual(result.health, "NO_SNAPSHOT")
        self.assertFalse(result.authority_usable)
        self.assertEqual(result.eligible_rows, 0)


if __name__ == "__main__":
    unittest.main()
