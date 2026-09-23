import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "phase3_collect_fast_lane.py"
spec = importlib.util.spec_from_file_location("phase3_collect_fast_lane", SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def test_duplicate_diagnostics_reports_only_repeated_external_ids():
    rows = [
        {"external_id": "11", "minute": 67},
        {"external_id": "11", "minute": 68},
        {"external_id": "12", "minute": 22},
        {"external_id": None, "minute": 10},
    ]
    assert collector.duplicate_observation_ids(rows) == ["11"]


def test_coverage_meta_exposes_mapped_unmapped_and_missing_verified_ids():
    joined = [{"external_id": "11", "hkjc_event_id": "FB1"}]
    unmapped = [
        {"external_id": "12", "reason": "IDENTITY_GAP"},
        {"external_id": "999", "reason": "NOT_A_TARGET"},
    ]
    meta = collector.coverage_meta({"11", "12", "13"}, {"11", "12"}, joined, unmapped)
    assert meta == {
        "mapped_rows": 1,
        "unmapped_count": 1,
        "unmapped_external_ids": ["12"],
        "missing_target_ids": ["13"],
    }


def test_coverage_meta_deduplicates_unmapped_ids_without_fuzzy_promotion():
    meta = collector.coverage_meta(
        {"12"},
        {"12"},
        [],
        [{"external_id": "12"}, {"external_id": "12"}],
    )
    assert meta["mapped_rows"] == 0
    assert meta["unmapped_count"] == 1
    assert meta["unmapped_external_ids"] == ["12"]
    assert meta["missing_target_ids"] == []


def test_last_good_meta_exposes_consumer_state_for_valid_live_cache(tmp_path, monkeypatch):
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "last_good.json"
    path.write_text(json.dumps({
        "health": "FRESH_LIVE",
        "live_rows": 2,
        "fast_snapshot_at": (now - timedelta(seconds=7)).isoformat(),
    }))
    monkeypatch.setattr(collector, "LAST_GOOD", path)
    assert collector.last_good_meta(now) == {
        "last_good_at": "2026-09-23T11:59:53+00:00",
        "last_good_age_seconds": 7.0,
        "last_good_health": "FRESH_LIVE",
        "last_good_live_rows": 2,
    }
    assert path.exists()


def test_last_good_meta_purges_non_live_cache_and_exposes_empty_state(tmp_path, monkeypatch):
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "last_good.json"
    path.write_text(json.dumps({
        "health": "FRESH_PARTIAL_OR_TERMINAL",
        "live_rows": 0,
        "fast_snapshot_at": now.isoformat(),
    }))
    monkeypatch.setattr(collector, "LAST_GOOD", path)
    assert collector.last_good_meta(now) == {
        "last_good_at": None,
        "last_good_age_seconds": None,
        "last_good_health": None,
        "last_good_live_rows": 0,
    }
    assert not path.exists()


def test_board_dates_do_not_speculatively_fetch_adjacent_days_without_kickoff():
    now = datetime(2026, 9, 23, 0, 5, tzinfo=timezone.utc)
    assert collector.board_dates(now, []) == ["20260923"]
    assert collector.board_dates(now, [{"external_id": "11"}]) == ["20260923"]


def test_board_dates_add_only_dates_supported_by_verified_kickoff():
    now = datetime(2026, 9, 23, 0, 5, tzinfo=timezone.utc)
    verified = [
        {"external_id": "11", "kickoff_utc": "2026-09-22T23:55:00Z"},
        {"external_id": "12", "kickoff_utc": "2026-09-24T00:10:00+00:00"},
        {"external_id": "13", "kickoff_utc": "2026-09-23T12:00:00Z"},
    ]
    assert collector.board_dates(now, verified) == ["20260923", "20260922", "20260924"]


def test_terminal_retention_cannot_trigger_historical_board_crawl():
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    verified = [
        {"external_id": "old", "kickoff_utc": "2026-09-10T12:00:00Z"},
        {"external_id": "boundary", "kickoff_utc": "2026-09-22T23:55:00Z"},
    ]
    assert collector.board_dates(now, verified) == ["20260923", "20260922"]


def test_naive_kickoff_is_not_used_to_guess_board_timezone():
    now = datetime(2026, 9, 23, 0, 5, tzinfo=timezone.utc)
    assert collector.board_dates(now, [{"external_id": "11", "kickoff_utc": "2026-09-22T23:55:00"}]) == ["20260923"]


def test_fotmob_date_uses_supplied_utc_clock_without_local_timezone_drift():
    before_midnight = datetime(2026, 9, 22, 23, 59, 59, tzinfo=timezone.utc)
    after_midnight = datetime(2026, 9, 23, 0, 0, 1, tzinfo=timezone.utc)
    assert collector.fotmob_date(before_midnight) == "20260922"
    assert collector.fotmob_date(after_midnight) == "20260923"