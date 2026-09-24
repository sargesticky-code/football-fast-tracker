import unittest
from datetime import datetime, timezone

from scripts.sofascore_h2h import (
    FixtureIdentity,
    match_scheduled_event,
    normalize_h2h_events,
    normalize_identity_name,
    summarize_h2h,
)


class SofascoreH2HTests(unittest.TestCase):
    def test_identity_normalization_keeps_cohort_markers(self):
        self.assertEqual(normalize_identity_name("Paris Saint-Germain F.C."), "paris saint germain f c")
        self.assertNotEqual(normalize_identity_name("Arsenal Women"), normalize_identity_name("Arsenal"))

    def test_exact_fixture_pair_maps_to_one_event(self):
        fixture = FixtureIdentity(
            hkjc_event_id="FB9999",
            kickoff=datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc),
            home="Paris Saint-Germain",
            away="Marseille",
        )
        payload = {
            "events": [
                {
                    "id": 123,
                    "startTimestamp": int(datetime(2026, 9, 24, 19, 5, tzinfo=timezone.utc).timestamp()),
                    "homeTeam": {"id": 1, "name": "Paris Saint-Germain"},
                    "awayTeam": {"id": 2, "name": "Marseille"},
                    "tournament": {"name": "Ligue 1"},
                }
            ]
        }
        result = match_scheduled_event(fixture, payload)
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.event_id, 123)
        self.assertEqual(result.home_team_id, 1)
        self.assertEqual(result.away_team_id, 2)

    def test_verified_alias_can_map_source_name_without_fuzzy_guess(self):
        fixture = FixtureIdentity(
            hkjc_event_id="FB9998",
            kickoff=datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc),
            home="Manchester United",
            away="Manchester City",
        )
        payload = {
            "events": [
                {
                    "id": 456,
                    "startTimestamp": int(datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc).timestamp()),
                    "homeTeam": {"id": 10, "name": "Man Utd"},
                    "awayTeam": {"id": 11, "name": "Man City"},
                }
            ]
        }
        result = match_scheduled_event(
            fixture,
            payload,
            verified_aliases={
                "Manchester United": ["Man Utd"],
                "Manchester City": ["Man City"],
            },
        )
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.event_id, 456)

    def test_cohort_mismatch_is_not_forced(self):
        fixture = FixtureIdentity(
            hkjc_event_id="FB9997",
            kickoff=datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc),
            home="Arsenal Women",
            away="Chelsea Women",
        )
        payload = {
            "events": [
                {
                    "id": 789,
                    "startTimestamp": int(datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc).timestamp()),
                    "homeTeam": {"id": 20, "name": "Arsenal"},
                    "awayTeam": {"id": 21, "name": "Chelsea"},
                }
            ]
        }
        self.assertEqual(match_scheduled_event(fixture, payload).status, "UNMAPPED")

    def test_h2h_reorients_reverse_home_away(self):
        cutoff = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
        payload = {
            "events": [
                {
                    "id": 1001,
                    "startTimestamp": int(datetime(2026, 4, 1, 18, 0, tzinfo=timezone.utc).timestamp()),
                    "status": {"code": 100},
                    "homeTeam": {"id": 2, "name": "Away Club"},
                    "awayTeam": {"id": 1, "name": "Home Club"},
                    "homeScore": {"current": 3},
                    "awayScore": {"current": 1},
                    "tournament": {"name": "League"},
                },
                {
                    "id": 1002,
                    "startTimestamp": int(datetime(2025, 12, 1, 18, 0, tzinfo=timezone.utc).timestamp()),
                    "status": {"type": "finished"},
                    "homeTeam": {"id": 1, "name": "Home Club"},
                    "awayTeam": {"id": 2, "name": "Away Club"},
                    "homeScore": {"current": 2},
                    "awayScore": {"current": 0},
                    "tournament": {"name": "League"},
                },
            ]
        }
        meetings = normalize_h2h_events(
            payload,
            current_home_team_id=1,
            current_away_team_id=2,
            current_kickoff=cutoff,
        )
        self.assertEqual(len(meetings), 2)
        self.assertEqual(meetings[0]["current_home_goals"], 1)
        self.assertEqual(meetings[0]["current_away_goals"], 3)
        self.assertEqual(meetings[0]["result"], "A")
        self.assertEqual(meetings[1]["result"], "H")

        summary = summarize_h2h(meetings)
        self.assertEqual(summary["h2h_games"], 2)
        self.assertEqual(summary["home_wins"], 1)
        self.assertEqual(summary["away_wins"], 1)
        self.assertEqual(summary["last5"], "AH")
        self.assertEqual(summary["quality"], "H2H_OK")

    def test_no_history_is_not_failure(self):
        summary = summarize_h2h([])
        self.assertEqual(summary["quality"], "NO_HISTORY")
        self.assertEqual(summary["h2h_games"], 0)


if __name__ == "__main__":
    unittest.main()
