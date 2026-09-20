from datetime import datetime

from multibetter.aliasing.cache import AliasCacheRow
from multibetter.matching.fixture_resolver import LearnedAlias
from multibetter.scripts.update_verified_alias_cache import apply_learned_file


def test_apply_deterministic_learning_to_alias_cache():
    merged = apply_learned_file(
        [],
        [
            (
                LearnedAlias(
                    "Man City",
                    "Manchester City",
                    "UNIQUE_DATE_TIME_LEAGUE_FIXTURE",
                ),
                datetime(2026, 9, 20, 8, 0),
            )
        ],
    )
    assert len(merged) == 1
    assert merged[0].alias == "Man City"
    assert merged[0].target == "Manchester City"
    assert merged[0].status == "AUTO_DETERMINISTIC"


def test_existing_cache_stays_single_row():
    merged = apply_learned_file(
        [
            AliasCacheRow(
                "Man City",
                "Manchester City",
                status="AUTO_DETERMINISTIC",
                first_seen="2026-09-20T08:00:00",
                last_seen="2026-09-20T08:00:00",
            )
        ],
        [
            (
                LearnedAlias(
                    "Man City",
                    "Manchester City",
                    "UNIQUE_DATE_TIME_LEAGUE_FIXTURE",
                ),
                datetime(2026, 9, 21, 8, 0),
            )
        ],
    )
    assert len(merged) == 1
    assert merged[0].observation_count == 2
