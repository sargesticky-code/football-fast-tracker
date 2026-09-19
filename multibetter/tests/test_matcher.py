from datetime import datetime

from multibetter.matching.matcher import match_prediction
from multibetter.models import CanonicalFixture, MatchDecision, SourcePrediction


def fixture(
    *,
    hkjc_home="白禮頓",
    hkjc_away="阿仙奴",
    forebet_home="Brighton",
    forebet_away="Arsenal",
):
    return CanonicalFixture(
        event_id="FBTEST",
        kickoff=datetime(2026, 9, 20, 20, 0),
        competition="Premier League",
        hkjc_home=hkjc_home,
        hkjc_away=hkjc_away,
        forebet_home=forebet_home,
        forebet_away=forebet_away,
        forebet_competition="Premier League",
    )


def test_source_matches_forebet_not_hkjc():
    result = match_prediction(
        fixture(),
        SourcePrediction(
            source="APWIN",
            kickoff=datetime(2026, 9, 20, 20, 0),
            competition="Premier League",
            home="Brighton",
            away="Arsenal",
        ),
    )
    assert result.decision == MatchDecision.EXACT
    assert result.event_id == "FBTEST"
    assert result.forebet_home == "Brighton"


def test_rejects_u21_false_positive():
    result = match_prediction(
        fixture(),
        SourcePrediction(
            source="APWIN",
            kickoff=datetime(2026, 9, 20, 20, 0),
            competition="Premier League 2",
            home="Birmingham City U21",
            away="Arsenal U21",
        ),
    )
    assert result.decision == MatchDecision.REJECT
    assert result.reason == "TEAM_CLASS_MISMATCH"


def test_source_alias_resolves_to_forebet():
    result = match_prediction(
        fixture(
            hkjc_home="奧丹斯",
            hkjc_away="米迪蘭特",
            forebet_home="Odense",
            forebet_away="Midtjylland",
        ),
        SourcePrediction(
            source="APWIN",
            kickoff=datetime(2026, 9, 20, 20, 0),
            competition="Premier League",
            home="OB",
            away="Midtjylland",
        ),
        source_to_forebet_aliases={"OB": "Odense"},
    )
    assert result.decision == MatchDecision.ALIAS
    assert result.event_id == "FBTEST"
