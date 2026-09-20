from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from multibetter.models import (
    CanonicalFixture,
    MatchDecision,
    MatchResult,
    MultiSourceFixture,
)
from multibetter.normalization.teams import canonicalize_team, classify_team, normalize_text


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
        if fixture.home_class != fixture.home_class.UNKNOWN
        else classify_team(fixture.forebet_home)
    )
    our_away_class = (
        fixture.away_class
        if fixture.away_class != fixture.away_class.UNKNOWN
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

    our_home, _ = canonicalize_team(fixture.forebet_home)
    our_away, _ = canonicalize_team(fixture.forebet_away)

    github_home, home_alias = canonicalize_team(
        multi.github_forebet_home,
        forebet_bridge_aliases,
    )
    github_away, away_alias = canonicalize_team(
        multi.github_forebet_away,
        forebet_bridge_aliases,
    )

    if our_home != github_home or our_away != github_away:
        return MatchResult(MatchDecision.REJECT, 0.0, "FOREBET_BRIDGE_MISMATCH")

    used_alias = (
        home_alias
        or away_alias
        or normalize_text(fixture.forebet_home) != normalize_text(multi.github_forebet_home)
        or normalize_text(fixture.forebet_away) != normalize_text(multi.github_forebet_away)
    )

    if used_alias:
        return MatchResult(
            MatchDecision.ALIAS,
            0.95,
            "GITHUB_FOREBET_TO_OUR_FOREBET_ALIAS",
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
