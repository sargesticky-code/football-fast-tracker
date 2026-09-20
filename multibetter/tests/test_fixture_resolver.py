from datetime import datetime

from multibetter.matching.fixture_resolver import (
    FixtureResolveStatus,
    build_fixture_index,
    resolve_fixture_cache_first,
)
from multibetter.models import CanonicalFixture, MultiSourceFixture


def f(event_id, hour, home, away, competition="EPL"):
    return CanonicalFixture(
        event_id=event_id,
        kickoff=datetime(2026, 9, 20, hour, 0),
        competition=competition,
        hkjc_home=home,
        hkjc_away=away,
        forebet_home=home,
        forebet_away=away,
        forebet_competition=competition,
    )


def test_alias_cache_is_fast_path():
    fixtures = [f("FB1", 21, "Manchester City", "Sunderland")]
    multi = MultiSourceFixture(
        kickoff=datetime(2026, 9, 20, 21, 0),
        github_forebet_home="Man City",
        github_forebet_away="Sunderland",
        github_forebet_competition="EPL",
    )
    result = resolve_fixture_cache_first(
        multi,
        fixtures,
        verified_aliases={"Man City": "Manchester City"},
    )
    assert result.status == FixtureResolveStatus.FAST_ALIAS
    assert result.fixture.event_id == "FB1"
    assert not result.learned_aliases


def test_unique_time_league_fixture_learns_alias_once():
    fixtures = [f("FB1", 21, "Manchester City", "Sunderland")]
    multi = MultiSourceFixture(
        kickoff=datetime(2026, 9, 20, 21, 0),
        github_forebet_home="Man City",
        github_forebet_away="Sunderland AFC",
        github_forebet_competition="EPL",
    )
    result = resolve_fixture_cache_first(multi, fixtures)
    assert result.status == FixtureResolveStatus.DETERMINISTIC_UNIQUE
    learned = {(x.alias, x.target) for x in result.learned_aliases}
    assert ("Man City", "Manchester City") in learned
    assert ("Sunderland AFC", "Sunderland") in learned


def test_time_matters():
    fixtures = [f("FB1", 21, "Manchester City", "Sunderland")]
    multi = MultiSourceFixture(
        kickoff=datetime(2026, 9, 20, 20, 0),
        github_forebet_home="Man City",
        github_forebet_away="Sunderland",
        github_forebet_competition="EPL",
    )
    result = resolve_fixture_cache_first(multi, fixtures)
    assert result.status == FixtureResolveStatus.NO_FIXTURE


def test_same_time_league_uses_team_pair_only_in_small_bucket():
    fixtures = [
        f("FB1", 21, "Manchester City", "Sunderland"),
        f("FB2", 21, "Bournemouth", "Liverpool"),
        f("FB3", 21, "Leeds", "Crystal Palace"),
    ]
    multi = MultiSourceFixture(
        kickoff=datetime(2026, 9, 20, 21, 0),
        github_forebet_home="Man City",
        github_forebet_away="Sunderland AFC",
        github_forebet_competition="EPL",
    )
    index = build_fixture_index(fixtures)
    result = resolve_fixture_cache_first(
        multi,
        fixtures,
        fixture_index=index,
    )
    assert result.status == FixtureResolveStatus.DETERMINISTIC_TEAM_PAIR
    assert result.fixture.event_id == "FB1"
    assert result.candidate_count == 3


def test_team_class_conflict_blocks_auto_learning():
    fixtures = [f("FB1", 21, "Arsenal", "Chelsea")]
    multi = MultiSourceFixture(
        kickoff=datetime(2026, 9, 20, 21, 0),
        github_forebet_home="Arsenal U21",
        github_forebet_away="Chelsea U21",
        github_forebet_competition="EPL",
    )
    result = resolve_fixture_cache_first(multi, fixtures)
    assert result.status == FixtureResolveStatus.CONFLICT
