import unittest
from datetime import datetime,timezone,timedelta
from scripts.phase3_collect_fotmob_identity import _cooldown,SOURCE_COOLDOWN_SECONDS

class SourceHealthTests(unittest.TestCase):
    def test_recent_block_is_cooled_down(self):
        now=datetime(2026,9,21,16,0,tzinfo=timezone.utc)
        state={"SOFASCORE":{"blocked_at":(now-timedelta(minutes=5)).isoformat()}}
        blocked,age=_cooldown(state,now,"SOFASCORE")
        self.assertTrue(blocked); self.assertEqual(age,300)

    def test_old_block_retries(self):
        now=datetime(2026,9,21,16,0,tzinfo=timezone.utc)
        state={"SOFASCORE":{"blocked_at":(now-timedelta(seconds=SOURCE_COOLDOWN_SECONDS+1)).isoformat()}}
        blocked,_=_cooldown(state,now,"SOFASCORE")
        self.assertFalse(blocked)

    def test_missing_or_bad_timestamp_does_not_permanently_block(self):
        now=datetime(2026,9,21,16,0,tzinfo=timezone.utc)
        self.assertFalse(_cooldown({},now,"SOFASCORE")[0])
        self.assertFalse(_cooldown({"SOFASCORE":{"blocked_at":"bad"}},now,"SOFASCORE")[0])

    def test_provider_cooldowns_are_independent(self):
        now=datetime(2026,9,21,16,0,tzinfo=timezone.utc)
        state={"ESPN":{"blocked_at":(now-timedelta(minutes=1)).isoformat()}}
        self.assertTrue(_cooldown(state,now,"ESPN")[0])
        self.assertFalse(_cooldown(state,now,"SOFASCORE")[0])

if __name__=="__main__": unittest.main()
