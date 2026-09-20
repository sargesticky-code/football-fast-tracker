from __future__ import annotations

from datetime import datetime
from typing import Iterable

from multibetter.models import MultiSourceFixture, SourcePrediction


def build_multi_fixture(
    *,
    kickoff: datetime,
    github_forebet_home: str,
    github_forebet_away: str,
    github_forebet_competition: str | None = None,
    predictions: Iterable[SourcePrediction] = (),
    external_fixture_id: str | None = None,
) -> MultiSourceFixture:
    """Create the Multibetter boundary object from GitHub multi-source output.

    Important: this function does not rematch BetClan/Statarea/etc. to Forebet.
    That association belongs to the external framework. Multibetter receives the
    already-grouped source rows plus the external framework's Forebet identity.
    """

    return MultiSourceFixture(
        kickoff=kickoff,
        github_forebet_home=github_forebet_home,
        github_forebet_away=github_forebet_away,
        github_forebet_competition=github_forebet_competition,
        predictions=tuple(predictions),
        external_fixture_id=external_fixture_id,
    )
