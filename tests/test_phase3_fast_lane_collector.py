import importlib.util
from datetime import datetime, timezone
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


def test_board_dates_are_bounded_to_primary_plus_adjacent_days():
    now = datetime(2026, 9, 23, 0, 5, tzinfo=timezone.utc)
    assert collector.board_dates(now, []) == ["20260923"]
    assert collector.board_dates(now, [{"external_id": "11"}]) == [
        "20260923",
        "20260922",
        "20260924",
    ]


def test_fotmob_date_uses_supplied_utc_clock_without_local_timezone_drift():
    before_midnight = datetime(2026, 9, 22, 23, 59, 59, tzinfo=timezone.utc)
    after_midnight = datetime(2026, 9, 23, 0, 0, 1, tzinfo=timezone.utc)
    assert collector.fotmob_date(before_midnight) == "20260922"
    assert collector.fotmob_date(after_midnight) == "20260923"
