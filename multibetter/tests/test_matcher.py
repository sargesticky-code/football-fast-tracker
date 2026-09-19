from datetime import datetime

from multibetter.matching.matcher import match_prediction
from multibetter.models import CanonicalFixture, MatchDecision, SourcePrediction


def fixture(home="Brighton", away="Arsenal"):
    return CanonicalFixture(
        event_id="FBTEST",
        kickoff=datetime(2026, 9, 20, 20, 0),
        competition="Premier League",
        home=home,
        away=away,
    )


def test_exact_match():
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


def test_approved_alias():
    result = match_prediction(
        fixture("Odense", "Midtjylland"),
        SourcePrediction(
            source="APWIN",
            kickoff=datetime(2026, 9, 20, 20, 0),
            competition="Premier League",
            home="OB",
            away="Midtjylland",
        ),
        team_aliases={"OB": "Odense"},
    )
    assert result.decision == MatchDecision.ALIAS
