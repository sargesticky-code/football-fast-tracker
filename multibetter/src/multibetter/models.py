from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Mapping


class Market(str, Enum):
    HDA = "HDA"
    GOALS = "GOALS"
    CORNERS = "CORNERS"
    BTTS = "BTTS"


class TeamClass(str, Enum):
    SENIOR = "SENIOR"
    WOMEN = "WOMEN"
    YOUTH = "YOUTH"
    RESERVE = "RESERVE"
    B_TEAM = "B_TEAM"
    UNKNOWN = "UNKNOWN"


class MatchDecision(str, Enum):
    EXACT = "EXACT"
    ALIAS = "ALIAS"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


@dataclass(frozen=True)
class CanonicalFixture:
    """OUR Forebet fixture already linked to HKJC."""

    event_id: str
    kickoff: datetime
    competition: str

    hkjc_home: str
    hkjc_away: str

    forebet_home: str
    forebet_away: str

    forebet_competition: str | None = None
    home_class: TeamClass = TeamClass.UNKNOWN
    away_class: TeamClass = TeamClass.UNKNOWN


@dataclass(frozen=True)
class SourcePrediction:
    source: str
    kickoff: datetime | None
    competition: str | None
    home: str
    away: str

    fixture_date: date | None = None
    source_url: str | None = None
    fetched_at: datetime | None = None

    probabilities: Mapping[str, float] = field(default_factory=dict)
    recommendations: Mapping[str, str] = field(default_factory=dict)
    odds: Mapping[str, float] = field(default_factory=dict)

    predicted_score: str | None = None
    market_label: str | None = None
    source_kickoff_text: str | None = None


@dataclass(frozen=True)
class MultiSourceFixture:
    """A fixture already aligned inside the external GitHub multi-source framework.

    Multibetter trusts the external framework to associate its individual source rows.
    We only bridge the fixture's Forebet identity to OUR Forebet.
    """

    kickoff: datetime
    github_forebet_home: str
    github_forebet_away: str
    github_forebet_competition: str | None = None
    predictions: tuple[SourcePrediction, ...] = ()
    external_fixture_id: str | None = None


@dataclass(frozen=True)
class MatchResult:
    decision: MatchDecision
    confidence: float
    reason: str
    event_id: str | None = None
    forebet_home: str | None = None
    forebet_away: str | None = None
