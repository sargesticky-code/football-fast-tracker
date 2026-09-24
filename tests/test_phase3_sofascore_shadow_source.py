from phase3.sofascore_shadow_source import normalize_live_board


def test_verified_only_board_join_and_freshness():
    payload = {"events": [
        {"id": 11, "status": {"type": "inprogress"}, "homeScore": {"current": 2}, "awayScore": {"current": 1}, "changes": {"changeTimestamp": 1790280000}},
        {"id": 12, "status": {"type": "inprogress"}, "homeScore": {"current": 0}, "awayScore": {"current": 0}},
    ]}
    out = normalize_live_board(payload, {"11": "FB11"})
    assert out["board_rows"] == 2
    assert out["unmapped_rows"] == 1
    assert out["collision_rows"] == 0
    assert len(out["rows"]) == 1
    row = out["rows"][0]
    assert row["hkjc_match_id"] == "FB11"
    assert row["identity_status"] == "VERIFIED"
    assert row["status"] == "LIVE"
    assert (row["home_score"], row["away_score"]) == (2, 1)
    assert out["source_updated_at"] == row["source_updated_at"]


def test_duplicate_hkjc_mapping_fails_closed_as_collision():
    payload = {"events": [
        {"id": 21, "status": {"type": "inprogress"}},
        {"id": 22, "status": {"type": "inprogress"}},
    ]}
    out = normalize_live_board(payload, {"21": "FB1", "22": "FB1"})
    assert len(out["rows"]) == 1
    assert out["collision_rows"] == 1


def test_no_verified_mapping_means_no_enrichment():
    out = normalize_live_board({"events": [{"id": 99, "status": {"type": "inprogress"}}]}, {})
    assert out["rows"] == []
    assert out["unmapped_rows"] == 1
