from datetime import datetime, timezone

from phase3.freshness_metrics import freshness_evidence, summarize_freshness


NOW = datetime(2026, 10, 3, 4, 45, 0, tzinfo=timezone.utc)


def test_freshness_evidence_keeps_score_and_minute_separate():
    evidence = freshness_evidence(
        {
            "source_updated_at": "2026-10-03T04:44:55+00:00",
            "score_updated_at": "2026-10-03T04:44:50+00:00",
            "minute_updated_at": "2026-10-03T04:44:40+00:00",
        },
        NOW,
    )
    assert evidence["snapshot_age_seconds"] == 5.0
    assert evidence["score_age_seconds"] == 10.0
    assert evidence["minute_age_seconds"] == 20.0


def test_missing_provider_timestamps_remain_unavailable():
    evidence = freshness_evidence({}, NOW)
    assert evidence["snapshot_age_seconds"] is None
    assert evidence["score_age_seconds"] is None
    assert evidence["minute_age_seconds"] is None


def test_freshness_summary_ignores_unavailable_without_inventing_age():
    summary = summarize_freshness(
        [
            {"score_age_seconds": 5, "minute_age_seconds": 10},
            {"score_age_seconds": None, "minute_age_seconds": None},
            {"score_age_seconds": 15, "minute_age_seconds": 30},
        ]
    )
    assert summary["median_score_age_seconds"] == 10.0
    assert summary["p95_score_age_seconds"] == 15.0
    assert summary["median_minute_age_seconds"] == 20.0
    assert summary["p95_minute_age_seconds"] == 30.0
