from datetime import datetime

import pytest

from multibetter.aliasing.cache import AliasCacheRow, merge_learned_aliases, touch_aliases
from multibetter.matching.fixture_resolver import LearnedAlias


def test_deterministic_alias_is_written_to_cache():
    rows = merge_learned_aliases(
        [],
        [LearnedAlias("Man City", "Manchester City", "UNIQUE_FIXTURE")],
        observed_at=datetime(2026, 9, 20, 8, 0),
    )
    assert rows[0].alias == "Man City"
    assert rows[0].target == "Manchester City"
    assert rows[0].status == "AUTO_DETERMINISTIC"


def test_reuse_updates_count_not_duplicate_row():
    existing = [
        AliasCacheRow(
            "Man City",
            "Manchester City",
            first_seen="2026-09-20T08:00:00",
            last_seen="2026-09-20T08:00:00",
        )
    ]
    rows = merge_learned_aliases(
        existing,
        [LearnedAlias("Man City", "Manchester City", "UNIQUE_FIXTURE")],
        observed_at=datetime(2026, 9, 21, 8, 0),
    )
    assert len(rows) == 1
    assert rows[0].observation_count == 2


def test_conflicting_relearn_is_blocked():
    with pytest.raises(ValueError):
        merge_learned_aliases(
            [AliasCacheRow("United", "Team A")],
            [LearnedAlias("United", "Team B", "UNIQUE_FIXTURE")],
            observed_at=datetime(2026, 9, 21, 8, 0),
        )


def test_cache_hit_updates_last_seen_and_usage_count():
    rows = touch_aliases(
        [
            AliasCacheRow(
                "Man City",
                "Manchester City",
                first_seen="2026-09-20T08:00:00",
                last_seen="2026-09-20T08:00:00",
                observation_count=3,
            )
        ],
        ["Man City"],
        observed_at=datetime(2026, 9, 25, 8, 0),
    )
    assert rows[0].observation_count == 4
    assert rows[0].last_seen == "2026-09-25T08:00:00"
