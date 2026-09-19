from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from multibetter.models import CanonicalFixture, MatchDecision, MatchResult, SourcePrediction
from multibetter.normalization.teams import canonicalize_team, classify_team, normalize_text


def _competition_equal(a: str | None, b: str | None, aliases: Mapping[str, str] | None) -> bool:
    if not a or not b:
        return True
    ca, _ = canonicalize_team(a, aliases)
    cb, _ = canonicalize_team(b, aliases)
    return ca == cb


def match_prediction(
    fixture: CanonicalFixture,
    candidate: SourcePrediction,
    *,
    source_to_forebet_aliases: Mapping[str, str] | None = None,
    competition_aliases: Mapping[str, str] | None = None,
    kickoff_tolerance: timedelta = timedelta(minutes=90),
) -> MatchResult:
    """Match an external source prediction to the Forebet reference layer.

    Important architecture rule:
    external sources DO NOT match directly to HKJC team names.

    Source team -> Forebet team key -> existing Forebet/HKJC bridge -> HKJC event ID.

    There is deliberately no fuzzy production fallback. Ambiguous candidates are
    rejected/reviewed instead of being silently linked to the wrong HKJC fixture.
    """

    source_home_class = classify_team(candidate.home)
    source_away_class = classify_team(candidate.away)

    reference_home_class = (
        fixture.home_class
        if fixture.home_class.value != "UNKNOWN"
        else classify_team(fixture.forebet_home)
    )
    reference_away_class = (
        fixture.away_class
        if fixture.away_class.value != "UNKNOWN"
        else classify_team(fixture.forebet_away)
    )

    if source_home_class != reference_home_class or source_away_class != reference_away_class:
        return MatchResult(MatchDecision.REJECT, 0.0, "TEAM_CLASS_MISMATCH")

    if candidate.kickoff is not None:
        if candidate.kickoff.date() != fixture.kickoff.date():
            return MatchResult(MatchDecision.REJECT, 0.0, "DATE_MISMATCH")
        if abs(candidate.kickoff - fixture.kickoff) > kickoff_tolerance:
            return MatchResult(MatchDecision.REJECT, 0.0, "KICKOFF_MISMATCH")

    reference_competition = fixture.forebet_competition or fixture.competition
    if not _competition_equal(reference_competition, candidate.competition, competition_aliases):
        return MatchResult(MatchDecision.REJECT, 0.0, "COMPETITION_MISMATCH")

    fh, _ = canonicalize_team(fixture.forebet_home)
    fa, _ = canonicalize_team(fixture.forebet_away)

    ch, ch_alias = canonicalize_team(candidate.home, source_to_forebet_aliases)
    ca, ca_alias = canonicalize_team(candidate.away, source_to_forebet_aliases)

    if fh != ch or fa != ca:
        return MatchResult(MatchDecision.REJECT, 0.0, "FOREBET_TEAM_MISMATCH")

    used_alias = (
        ch_alias
        or ca_alias
        or normalize_text(fixture.forebet_home) != normalize_text(candidate.home)
        or normalize_text(fixture.forebet_away) != normalize_text(candidate.away)
    )

    if used_alias:
        return MatchResult(
            MatchDecision.ALIAS,
            0.90,
            "SOURCE_TO_FOREBET_ALIAS",
            fixture.event_id,
            fixture.forebet_home,
            fixture.forebet_away,
        )

    return MatchResult(
        MatchDecision.EXACT,
        1.00,
        "FOREBET_EXACT_MATCH",
        fixture.event_id,
        fixture.forebet_home,
        fixture.forebet_away,
    )
