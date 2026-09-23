import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("phase3_fast_http", ROOT / "api" / "phase3_fast.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Reader:
    def __init__(self, state=None, error=None):
        self.state = state or {}
        self.error = error
        self.calls = 0

    def read(self):
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.state)


def base_state(**updates):
    state = {
        "health": "FRESH_LIVE",
        "fast_snapshot_at": "2026-09-24T00:00:00+00:00",
        "snapshot_age_seconds": 1.0,
        "request_failures": 0,
        "mapped_rows": 1,
        "live_rows": 1,
        "unmapped_count": 0,
        "unmapped_external_ids": [],
        "missing_target_ids": [],
        "duplicate_observation_ids": [],
        "rows": [{"external_id": "123", "status": "LIVE", "minute": 55, "home_score": 1, "away_score": 0}],
        "shared_cache": {"status": "HIT", "lease_age_seconds": 1.0, "upstream_refreshes": 1},
    }
    state.update(updates)
    return state


class FastHttpEndpointTests(unittest.TestCase):
    def test_projects_fresh_shared_state_without_bypass(self):
        reader = Reader(base_state())
        status, headers, body = MODULE.http_response(reader)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(body["display_state"], "FRESH")
        self.assertEqual(body["matches"][0]["minute"], 55)
        self.assertEqual(reader.calls, 1)

    def test_renders_identity_gap_fail_closed(self):
        reader = Reader(base_state(duplicate_observation_ids=["123"], rows=[], live_rows=0))
        status, _, body = MODULE.http_response(reader)
        self.assertEqual(status, 200)
        self.assertEqual(body["display_state"], "IDENTITY_GAP")
        self.assertEqual(body["matches"], [])
        self.assertEqual(reader.calls, 1)

    def test_renders_unmapped_fail_closed(self):
        reader = Reader(base_state(unmapped_count=1, unmapped_external_ids=["999"], rows=[], live_rows=0))
        status, _, body = MODULE.http_response(reader)
        self.assertEqual(status, 200)
        self.assertEqual(body["display_state"], "UNMAPPED")
        self.assertEqual(body["matches"], [])

    def test_service_failure_never_falls_back_to_source(self):
        reader = Reader(error=RuntimeError("shared service unavailable"))
        status, _, body = MODULE.http_response(reader)
        self.assertEqual(status, 503)
        self.assertEqual(body["display_state"], "REQUEST_FAILED")
        self.assertEqual(body["matches"], [])
        self.assertEqual(reader.calls, 1)

    def test_snapshot_refresh_has_no_network_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot.json"
            snapshot.write_text(json.dumps({"health": "FRESH_NO_LIVE_ROWS", "rows": [], "live_rows": 0}), encoding="utf-8")
            with patch.object(MODULE, "SNAPSHOT", snapshot):
                state = MODULE._read_snapshot()
        self.assertEqual(state["health"], "FRESH_NO_LIVE_ROWS")
        self.assertEqual(state["rows"], [])


if __name__ == "__main__":
    unittest.main()
