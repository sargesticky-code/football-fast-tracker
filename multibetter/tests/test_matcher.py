from datetime import datetime

from multibetter.matching.matcher import bridge_github_forebet_to_our_forebet
from multibetter.models import (
    CanonicalFixture,
    MatchDecision,
    MultiSourceFixture,
    SourcePrediction,
)


def our_fixture():
    return CanonicalFixture(
        event_id="FB1234",
        kickoff=datetime(2026, 9, 20, 20, 0),
        competition="Premier League",
        hkjc_home="白禮頓",
        hkjc_away="阿仙奴",
        forebet_home="Brighton",
        forebet_away="Arsenal",
        forebet_competition="Premier League",
    )


def test_exact_single_bridge():
    multi = MultiSourceFixture(
        kickoff=datetime(2026, 9, 20, 20, 0),
        github_forebet_home="Brighton",
        github_forebet_away="Arsenal",
        github_forebet_competition="Premier League",
    )

    result = bridge_github_forebet_to_our_forebet(our_fixture(), multi)

    assert result.decision == MatchDecision.EXACT
    assert result.event_id == "FB1234"


def test_other_sources_do_not_need_own_hkjc_aliases():
    multi = MultiSourceFixture(
        kickoff=datetime(2026, 9, 20, 20, 0),
        github_forebet_home="Brighton",
        github_forebet_away="Arsenal",
        github_forebet_competition="Premier League",
        predictions=(
            SourcePrediction(
                source="BETCLAN",
                kickoff=None,
                competition=None,
                home="Brighton Hove",
                away="Arsenal FC",
            ),
            SourcePrediction(
                source="STATAREA",
                kickoff=None,
                competition=None,
                home="Brighton",
                away="Arsenal",
            ),
        ),
    )

    result = bridge_github_forebet_to_our_forebet(our_fixture(), multi)

    assert result.decision == MatchDecision.EXACT
    assert len(multi.predictions) == 2


def test_small_forebet_bridge_alias_is_allowed():
    multi = MultiSourceFixture(
        kickoff=datetime(2026, 9, 20, 20, 0),
        github_forebet_home="Brighton Hove Albion",
        github_forebet_away="Arsenal",
        github_forebet_competition="Premier League",
    )

    result = bridge_github_forebet_to_our_forebet(
        our_fixture(),
        multi,
        forebet_bridge_aliases={"Brighton Hove Albion": "Brighton"},
    )

    assert result.decision == MatchDecision.ALIAS
    assert result.event_id == "FB1234"


def test_u21_forebet_fixture_cannot_bridge_to_senior_fixture():
    multi = MultiSourceFixture(
        kickoff=datetime(2026, 9, 20, 20, 0),
        github_forebet_home="Brighton U21",
        github_forebet_away="Arsenal U21",
        github_forebet_competition="Premier League 2",
    )

    result = bridge_github_forebet_to_our_forebet(our_fixture(), multi)

    assert result.decision == MatchDecision.REJECT
    assert result.reason == "TEAM_CLASS_MISMATCH"
