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
    team_aliases: Mapping[str, str] | None = None,
    competition_aliases: Mapping[str, str] | None = None,
    kickoff_tolerance: timedelta = timedelta(minutes=90),
) -> MatchResult:
    """Strict production matcher.

    There is deliberately no fuzzy fallback. Ambiguous records should be REVIEW/REJECT,
    never silently accepted into production.
    """

    source_home_class = classify_team(candidate.home)
    source_away_class = classify_team(candidate.away)
    fixture_home_class = fixture.home_class if fixture.home_class.value != "UNKNOWN" else classify_team(fixture.home)
    fixture_away_class = fixture.away_class if fixture.away_class.value != "UNKNOWN" else classify_team(fixture.away)

    if source_home_class != fixture_home_class or source_away_class != fixture_away_class:
        return MatchResult(MatchDecision.REJECT, 0.0, "TEAM_CLASS_MISMATCH")

    if candidate.kickoff is not None:
        if candidate.kickoff.date() != fixture.kickoff.date():
            return MatchResult(MatchDecision.REJECT, 0.0, "DATE_MISMATCH")
        if abs(candidate.kickoff - fixture.kickoff) > kickoff_tolerance:
            return MatchResult(MatchDecision.REJECT, 0.0, "KICKOFF_MISMATCH")

    if not _competition_equal(fixture.competition, candidate.competition, competition_aliases):
        return MatchResult(MatchDecision.REJECT, 0.0, "COMPETITION_MISMATCH")

    fh, _ = canonicalize_team(fixture.home, team_aliases)
    fa, _ = canonicalize_team(fixture.away, team_aliases)
    ch, ch_alias = canonicalize_team(candidate.home, team_aliases)
    ca, ca_alias = canonicalize_team(candidate.away, team_aliases)

    if fh != ch or fa != ca:
        return MatchResult(MatchDecision.REJECT, 0.0, "TEAM_NAME_MISMATCH")

    used_alias = ch_alias or ca_alias or normalize_text(fixture.home) != normalize_text(candidate.home) or normalize_text(fixture.away) != normalize_text(candidate.away)
    if used_alias:
        return MatchResult(MatchDecision.ALIAS, 0.90, "APPROVED_ALIAS_MATCH", fixture.event_id)

    return MatchResult(MatchDecision.EXACT, 1.00, "EXACT_MATCH", fixture.event_id)
