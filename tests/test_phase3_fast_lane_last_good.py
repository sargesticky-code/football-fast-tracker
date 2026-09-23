import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "phase3_collect_fast_lane.py"
spec = importlib.util.spec_from_file_location("phase3_collect_fast_lane_last_good", SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def test_last_good_meta_ages_only_genuine_fresh_live_snapshot(tmp_path, monkeypatch):
    state = tmp_path / "last_good.json"
    state.write_text(json.dumps({
        "health": "FRESH_LIVE",
        "live_rows": 1,
        "fast_snapshot_at": "2026-09-23T05:00:00+00:00",
    }))
    monkeypatch.setattr(collector, "LAST_GOOD", state)

    meta = collector.last_good_meta(datetime(2026, 9, 23, 5, 0, 7, tzinfo=timezone.utc))
    assert meta == {
        "last_good_at": "2026-09-23T05:00:00+00:00",
        "last_good_age_seconds": 7.0,
    }


def test_terminal_or_partial_snapshot_cannot_be_promoted_to_last_good(tmp_path, monkeypatch):
    state = tmp_path / "last_good.json"
    state.write_text(json.dumps({
        "health": "FRESH_PARTIAL_OR_TERMINAL",
        "live_rows": 0,
        "fast_snapshot_at": "2026-09-23T05:00:00+00:00",
    }))
    monkeypatch.setattr(collector, "LAST_GOOD", state)

    meta = collector.last_good_meta(datetime(2026, 9, 23, 5, 0, 7, tzinfo=timezone.utc))
    assert meta == {"last_good_at": None, "last_good_age_seconds": None}


def test_corrupt_last_good_state_fails_closed(tmp_path, monkeypatch):
    state = tmp_path / "last_good.json"
    state.write_text("{not-json")
    monkeypatch.setattr(collector, "LAST_GOOD", state)

    meta = collector.last_good_meta(datetime(2026, 9, 23, 5, 0, 7, tzinfo=timezone.utc))
    assert meta == {"last_good_at": None, "last_good_age_seconds": None}
