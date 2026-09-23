from phase3.fast_lane import fast_lane_health, join_verified_fast_rows, normalize_fotmob_board


def test_fotmob_stoppage_time_is_converted_to_elapsed_minute():
    payload = {
        "matches": [{
            "id": 77,
            "status": {"reason": {"short": "1st"}, "liveTime": {"short": "45+2'"}, "scoreStr": "1 - 0"},
        }]
    }
    rows = normalize_fotmob_board(payload, observed_at="2026-09-23T06:45:00+00:00")
    assert rows[0]["minute"] == 47


def test_stoppage_time_heartbeat_remains_fresh_live_after_verified_join():
    registry = [{"status": "VERIFIED", "source": "FOTMOB", "external_id": "77", "hkjc_event_id": "FBTEST"}]
    payload = {
        "matches": [{
            "id": 77,
            "status": {"reason": {"short": "2nd"}, "liveTime": {"short": "90+4'"}, "scoreStr": "2 - 1"},
        }]
    }
    board = normalize_fotmob_board(payload, observed_at="2026-09-23T06:45:00+00:00")
    joined, unmapped = join_verified_fast_rows(registry, board)
    assert not unmapped
    assert joined[0]["minute"] == 94
    health = fast_lane_health(joined, "2026-09-23T06:45:00+00:00", now="2026-09-23T06:45:05+00:00")
    assert health["health"] == "FRESH_LIVE"
    assert health["live_rows"] == 1


def test_malformed_stoppage_time_fails_closed():
    payload = {
        "matches": [{
            "id": 77,
            "status": {"reason": {"short": "1st"}, "liveTime": {"short": "45+bad'"}, "scoreStr": "1 - 0"},
        }]
    }
    rows = normalize_fotmob_board(payload, observed_at="2026-09-23T06:45:00+00:00")
    assert rows[0]["minute"] is None
