from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from multibetter.models import (
    CanonicalFixture,
    MatchDecision,
    MatchResult,
    MultiSourceFixture,
    TeamClass,
)
from multibetter.matching.forebet_bridge import BridgeStatus, bridge_team_name
from multibetter.normalization.teams import canonicalize_team, classify_team


def _competition_equal(
    a: str | None,
    b: str | None,
    aliases: Mapping[str, str] | None,
) -> bool:
    if not a or not b:
        return True
    ca, _ = canonicalize_team(a, aliases)
    cb, _ = canonicalize_team(b, aliases)
    return ca == cb


def bridge_github_forebet_to_our_forebet(
    fixture: CanonicalFixture,
    multi: MultiSourceFixture,
    *,
    forebet_bridge_aliases: Mapping[str, str] | None = None,
    competition_aliases: Mapping[str, str] | None = None,
    kickoff_tolerance: timedelta = timedelta(minutes=90),
) -> MatchResult:
    """Single production identity bridge.

    External source rows are NOT matched here. They are assumed to have already
    been grouped by the external GitHub multi-source framework.

    This function only answers:
        GitHub Forebet fixture == OUR Forebet fixture ?

    Once true, the existing OUR Forebet -> HKJC relationship supplies event_id.
    """

    github_home_class = classify_team(multi.github_forebet_home)
    github_away_class = classify_team(multi.github_forebet_away)

    our_home_class = (
        fixture.home_class
        if fixture.home_class != TeamClass.UNKNOWN
        else classify_team(fixture.forebet_home)
    )
    our_away_class = (
        fixture.away_class
        if fixture.away_class != TeamClass.UNKNOWN
        else classify_team(fixture.forebet_away)
    )

    if github_home_class != our_home_class or github_away_class != our_away_class:
        return MatchResult(MatchDecision.REJECT, 0.0, "TEAM_CLASS_MISMATCH")

    if multi.kickoff.date() != fixture.kickoff.date():
        return MatchResult(MatchDecision.REJECT, 0.0, "DATE_MISMATCH")

    both_naive = multi.kickoff.tzinfo is None and fixture.kickoff.tzinfo is None
    both_aware = multi.kickoff.tzinfo is not None and fixture.kickoff.tzinfo is not None
    if (both_naive or both_aware) and abs(multi.kickoff - fixture.kickoff) > kickoff_tolerance:
        return MatchResult(MatchDecision.REJECT, 0.0, "KICKOFF_MISMATCH")

    our_comp = fixture.forebet_competition or fixture.competition
    if not _competition_equal(
        our_comp,
        multi.github_forebet_competition,
        competition_aliases,
    ):
        return MatchResult(MatchDecision.REJECT, 0.0, "COMPETITION_MISMATCH")

    home_bridge = bridge_team_name(
        multi.github_forebet_home,
        {fixture.forebet_home},
        exception_aliases=forebet_bridge_aliases,
    )
    away_bridge = bridge_team_name(
        multi.github_forebet_away,
        {fixture.forebet_away},
        exception_aliases=forebet_bridge_aliases,
    )

    if home_bridge.status == BridgeStatus.CONFLICT or away_bridge.status == BridgeStatus.CONFLICT:
        return MatchResult(MatchDecision.REJECT, 0.0, "FOREBET_BRIDGE_CONFLICT")

    if home_bridge.status == BridgeStatus.CANDIDATE or away_bridge.status == BridgeStatus.CANDIDATE:
        return MatchResult(MatchDecision.REVIEW, 0.0, "FOREBET_BRIDGE_CANDIDATE")

    if (
        home_bridge.status == BridgeStatus.OUR_REFERENCE_MISSING
        or away_bridge.status == BridgeStatus.OUR_REFERENCE_MISSING
    ):
        return MatchResult(MatchDecision.REJECT, 0.0, "FOREBET_BRIDGE_MISMATCH")

    if home_bridge.status == BridgeStatus.ALIAS or away_bridge.status == BridgeStatus.ALIAS:
        return MatchResult(
            MatchDecision.ALIAS,
            0.95,
            "GITHUB_FOREBET_TO_OUR_FOREBET_VERIFIED_ALIAS",
            fixture.event_id,
            fixture.forebet_home,
            fixture.forebet_away,
        )

    return MatchResult(
        MatchDecision.EXACT,
        1.00,
        "GITHUB_FOREBET_TO_OUR_FOREBET_EXACT",
        fixture.event_id,
        fixture.forebet_home,
        fixture.forebet_away,
    )
