from phase3.fast_lane import fast_lane_health, fast_snapshot_age_seconds


def _live_row():
    return {
        "hkjc_event_id": "FB-FUTURE",
        "external_source": "FOTMOB",
        "external_id": "future-1",
        "status": "2ND",
        "minute": 68,
        "home_score": 1,
        "away_score": 0,
        "observed_at": "2026-09-23T12:00:10+00:00",
    }


def test_future_fast_snapshot_fails_closed_instead_of_appearing_fresh():
    observed_at = "2026-09-23T12:00:10+00:00"
    now = "2026-09-23T12:00:00+00:00"

    assert fast_snapshot_age_seconds(observed_at, now) is None
    health = fast_lane_health([_live_row()], observed_at, now=now)

    assert health["health"] == "NO_FAST_SNAPSHOT"
    assert health["snapshot_age_seconds"] is None
    assert health["live_rows"] == 1


def test_zero_age_snapshot_remains_eligible_for_fresh_live_health():
    observed_at = "2026-09-23T12:00:00+00:00"
    health = fast_lane_health([_live_row()], observed_at, now=observed_at)

    assert health["health"] == "FRESH_LIVE"
    assert health["snapshot_age_seconds"] == 0.0
    assert health["live_rows"] == 1
