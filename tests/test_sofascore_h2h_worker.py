import unittest
from datetime import datetime, timezone

from scripts.sofascore_h2h_worker import (
    build_sofascore_h2h,
    combine_schedules,
    schedule_dates,
)
from scripts.sofascore_h2h import FixtureIdentity


class FakeClient:
    def __init__(self):
        self.h2h_calls = []

    def scheduled_events(self, date):
        event = {
            "id": 333,
            "startTimestamp": int(datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc).timestamp()),
            "homeTeam": {"id": 1, "name": "Home Club"},
            "awayTeam": {"id": 2, "name": "Away Club"},
            "tournament": {"name": "Test League"},
        }
        return {"events": [event]}

    def h2h_events(self, event_id):
        self.h2h_calls.append(event_id)
        return {
            "events": [
                {
                    "id": 100,
                    "startTimestamp": int(datetime(2026, 3, 1, 19, 0, tzinfo=timezone.utc).timestamp()),
                    "status": {"code": 100},
                    "homeTeam": {"id": 2, "name": "Away Club"},
                    "awayTeam": {"id": 1, "name": "Home Club"},
                    "homeScore": {"current": 1},
                    "awayScore": {"current": 2},
                    "tournament": {"name": "Test League"},
                }
            ]
        }


class SofascoreWorkerTests(unittest.TestCase):
    def test_schedule_dates_covers_utc_and_hkt(self):
        fixture = FixtureIdentity(
            "FB1",
            datetime(2026, 9, 24, 18, 30, tzinfo=timezone.utc),
            "Home",
            "Away",
        )
        self.assertEqual(schedule_dates([fixture]), ["2026-09-24", "2026-09-25"])

    def test_combine_schedules_deduplicates_event_id(self):
        payload = {"events": [{"id": 1, "homeTeam": {}}, {"id": 2, "homeTeam": {}}]}
        combined = combine_schedules([payload, {"events": [{"id": 1, "awayTeam": {}}]}])
        ids = sorted(row["id"] for row in combined["events"])
        self.assertEqual(ids, [1, 2])

    def test_worker_fetches_h2h_only_for_verified_mapping(self):
        client = FakeClient()
        rows = [
            {
                "hkjc_event_id": "FB1",
                "kickoff_hkt": "2026-09-25T03:00:00+08:00",
                "home_id": "H1",
                "away_id": "A1",
                "home": "Home Club",
                "away": "Away Club",
                "tournament": "TST",
            },
            {
                "hkjc_event_id": "FB2",
                "kickoff_hkt": "2026-09-25T03:00:00+08:00",
                "home_id": "H2",
                "away_id": "A2",
                "home": "Different Home",
                "away": "Different Away",
                "tournament": "TST",
            },
        ]
        out = build_sofascore_h2h(rows, client=client, max_h2h_events=10)
        by_id = {row["hkjc_event_id"]: row for row in out}

        self.assertEqual(by_id["FB1"]["mapping_status"], "VERIFIED")
        self.assertEqual(by_id["FB1"]["quality"], "H2H_OK")
        self.assertEqual(by_id["FB1"]["h2h_games"], 1)
        self.assertEqual(by_id["FB1"]["last5"], "H")
        self.assertEqual(by_id["FB2"]["mapping_status"], "UNMAPPED")
        self.assertEqual(client.h2h_calls, [333])

    def test_budget_deferral_is_not_failure(self):
        client = FakeClient()
        rows = [
            {
                "hkjc_event_id": "FB1",
                "kickoff_hkt": "2026-09-25T03:00:00+08:00",
                "home_id": "H1",
                "away_id": "A1",
                "home": "Home Club",
                "away": "Away Club",
                "tournament": "TST",
            }
        ]
        out = build_sofascore_h2h(rows, client=client, max_h2h_events=0)
        self.assertEqual(out[0]["quality"], "DEFERRED_BUDGET")
        self.assertEqual(client.h2h_calls, [])


if __name__ == "__main__":
    unittest.main()
