from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from api import live_scores
from api.live_scores import HKT, provider_targets


class ProviderTargetsTest(unittest.TestCase):
  def test_provider_targets_keep_live_events_and_source_scoped_identity(self):
    now = datetime(2026, 10, 15, 10, 0, tzinfo=HKT)
    rows = [
        {
            "source": "FOOTBALL_LIVE_API_SELF_HOSTED",
            "source_match_id": "12345",
            "home": "Home FC",
            "away": "Away United",
            "league": "League One",
            "kickoff": now - timedelta(minutes=20),
            "status": "LIVE",
        },
        {
            "source": "FOTMOB_DAILY_BOARD",
            "source_match_id": "12345",
            "home": "Home FC",
            "away": "Away United",
            "kickoff": now - timedelta(minutes=20),
            "status": "LIVE",
            "_board_started": True,
        },
        {
            "source": "FOTMOB_DAILY_BOARD",
            "source_match_id": "future",
            "home": "Future Home",
            "away": "Future Away",
            "kickoff": now + timedelta(minutes=20),
            "status": "Not started",
        },
        {
            "source": "FOTMOB_DAILY_BOARD",
            "source_match_id": "finished",
            "home": "Finished Home",
            "away": "Finished Away",
            "kickoff": now - timedelta(minutes=30),
            "status": "FT",
            "_board_started": True,
        },
    ]

    targets = provider_targets(rows, now, "FOTMOB")

    self.assertEqual(len(targets), 1)
    self.assertEqual(targets[0]["event_id"], "FOTMOB:12345")
    self.assertEqual(targets[0]["source_event_id"], "12345")
    self.assertEqual(targets[0]["target_provider"], "FOTMOB")
    self.assertTrue(targets[0]["in_play"])


  def test_provider_targets_skip_unidentified_and_old_events(self):
    now = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
    rows = [
        {
            "source": "SOFASCORE",
            "source_match_id": "",
            "home": "No Id Home",
            "away": "No Id Away",
            "kickoff": now,
        },
        {
            "source": "FOTMOB_DAILY_BOARD",
            "source_match_id": "old",
            "home": "Old Home",
            "away": "Old Away",
            "kickoff": now - timedelta(hours=3),
            "status": "Scheduled",
        },
    ]

    self.assertEqual(provider_targets(rows, now, "SOFASCORE"), [])

  @patch("api.live_scores.sofascore_matches", return_value=[])
  @patch("api.live_scores.fetch_fotmob_detail", return_value={"content": {}, "header": {}})
  @patch("api.live_scores.primary_matches")
  def test_collect_uses_fotmob_event_ids_without_hkjc_targets(
      self, primary_matches, _detail, _sofascore):
    kickoff = datetime.now(HKT) - timedelta(minutes=5)
    event = {
        "source": "FOOTBALL_LIVE_API_SELF_HOSTED",
        "source_match_id": "fm-987",
        "home": "Home FC",
        "away": "Away United",
        "league": "League One",
        "kickoff": kickoff,
        "home_score": "1",
        "away_score": "0",
        "minute": "5",
        "status": "LIVE",
        "updated_at": kickoff.isoformat(),
        "_board_started": True,
        "_board_finished": False,
        "_board_cancelled": False,
    }
    primary_matches.return_value = ([event], [event])

    payload = live_scores.collect()

    self.assertEqual(payload["targetSource"], "FOTMOB")
    self.assertEqual(payload["targetCount"], 1)
    self.assertEqual(payload["matches"][0]["event_id"], "FOTMOB:fm-987")
    self.assertEqual(payload["matches"][0]["live_score"], "1-0")
    self.assertNotIn("hkjc_event_id", payload["matches"][0])

  @patch("api.live_scores.fetch_sofascore_statistics", return_value={})
  @patch("api.live_scores.sofascore_matches")
  @patch("api.live_scores.primary_matches", side_effect=RuntimeError("offline"))
  def test_collect_reconnects_to_sofascore_when_primary_board_fails(
      self, _primary, sofascore_matches, _stats):
    kickoff = datetime.now(HKT) - timedelta(minutes=5)
    event = {
        "source": "SOFASCORE",
        "source_match_id": "ss-321",
        "home": "Home FC",
        "away": "Away United",
        "kickoff": kickoff,
        "home_score": "0",
        "away_score": "0",
        "minute": "5",
        "status": "LIVE",
        "updated_at": kickoff.isoformat(),
    }
    sofascore_matches.return_value = [event]

    payload = live_scores.collect()

    self.assertEqual(payload["targetSource"], "SOFASCORE")
    self.assertEqual(payload["matches"][0]["event_id"], "SOFASCORE:ss-321")
    self.assertEqual(payload["health"]["primary"], "ERROR:RuntimeError")


if __name__ == "__main__":
    unittest.main()
