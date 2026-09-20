from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum
from typing import Iterable, Mapping, Sequence

from multibetter.aliasing.registry import resolve_verified_alias
from multibetter.models import CanonicalFixture, MultiSourceFixture
from multibetter.normalization.teams import classify_team, normalize_text


class FixtureResolveStatus(str, Enum):
    FAST_ALIAS = "FAST_ALIAS"
    DETERMINISTIC_UNIQUE = "DETERMINISTIC_UNIQUE"
    DETERMINISTIC_TEAM_PAIR = "DETERMINISTIC_TEAM_PAIR"
    AMBIGUOUS = "AMBIGUOUS"
    NO_FIXTURE = "NO_FIXTURE"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class LearnedAlias:
    alias: str
    target: str
    reason: str
    confidence: float = 1.0


@dataclass(frozen=True)
class FixtureResolveResult:
    status: FixtureResolveStatus
    fixture: CanonicalFixture | None
    learned_aliases: tuple[LearnedAlias, ...] = ()
    candidate_count: int = 0
    reason: str = ""


def _competition_key(value: str | None, aliases: Mapping[str, str] | None) -> str:
    raw = value or ""
    if aliases and raw in aliases:
        raw = aliases[raw]
    return normalize_text(raw)


def _time_key(value: datetime) -> str:
    return value.strftime("%H:%M")


def _coarse_key(
    kickoff: datetime,
    competition: str | None,
    competition_aliases: Mapping[str, str] | None,
) -> tuple[str, str, str]:
    return (
        kickoff.date().isoformat(),
        _time_key(kickoff),
        _competition_key(competition, competition_aliases),
    )


def build_fixture_index(
    fixtures: Iterable[CanonicalFixture],
    *,
    competition_aliases: Mapping[str, str] | None = None,
) -> dict[tuple[str, str, str], list[CanonicalFixture]]:
    index: dict[tuple[str, str, str], list[CanonicalFixture]] = {}
    for fixture in fixtures:
        comp = fixture.forebet_competition or fixture.competition
        key = _coarse_key(fixture.kickoff, comp, competition_aliases)
        index.setdefault(key, []).append(fixture)
    return index


def build_time_index(
    fixtures: Iterable[CanonicalFixture],
) -> dict[tuple[str, str], list[CanonicalFixture]]:
    """Fallback index for feeds that do not yet carry competition."""
    index: dict[tuple[str, str], list[CanonicalFixture]] = {}
    for fixture in fixtures:
        key = (
            fixture.kickoff.date().isoformat(),
            _time_key(fixture.kickoff),
        )
        index.setdefault(key, []).append(fixture)
    return index


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(
        None,
        normalize_text(a),
        normalize_text(b),
    ).ratio() * 100.0


def _orientation_scores(
    multi: MultiSourceFixture,
    fixture: CanonicalFixture,
) -> tuple[float, float]:
    """Return direct(home->home, away->away) and swapped pair scores."""
    direct = (
        _ratio(multi.github_forebet_home, fixture.forebet_home)
        + _ratio(multi.github_forebet_away, fixture.forebet_away)
    ) / 2.0
    swapped = (
        _ratio(multi.github_forebet_home, fixture.forebet_away)
        + _ratio(multi.github_forebet_away, fixture.forebet_home)
    ) / 2.0
    return direct, swapped


def _orientation_conflict(
    multi: MultiSourceFixture,
    fixture: CanonicalFixture,
    *,
    home_target: str | None,
    away_target: str | None,
    orientation_margin: float,
) -> str | None:
    """Protect alias learning from home/away reversal.

    Explicit HOME/AWAY sources are role-strict.
    Inferred team1/team2 sources use left=home/right=away by default, but an
    obviously stronger swapped pairing is not auto-learned.
    """
    if home_target is not None and home_target == fixture.forebet_away:
        return "HOME_TARGET_MATCHES_AWAY"
    if away_target is not None and away_target == fixture.forebet_home:
        return "AWAY_TARGET_MATCHES_HOME"
    if home_target is not None and home_target != fixture.forebet_home:
        return "HOME_TARGET_WRONG_SIDE"
    if away_target is not None and away_target != fixture.forebet_away:
        return "AWAY_TARGET_WRONG_SIDE"

    direct, swapped = _orientation_scores(multi, fixture)
    if swapped >= direct + orientation_margin:
        return (
            "HOME_AWAY_SWAP_CONFLICT:"
            f"direct={direct:.1f},swapped={swapped:.1f},"
            f"explicit={multi.home_away_explicit}"
        )

    return None


def _learn_if_needed(
    source_name: str,
    target_name: str,
    *,
    existing_aliases: Mapping[str, str],
    reason: str,
) -> LearnedAlias | None:
    if source_name == target_name:
        return None

    existing = existing_aliases.get(source_name)
    if existing is not None:
        if existing != target_name:
            raise ValueError(
                f"Alias conflict: {source_name!r} -> {existing!r}, "
                f"cannot relearn as {target_name!r}"
            )
        return None

    if classify_team(source_name) != classify_team(target_name):
        raise ValueError(
            f"Team-class conflict: {source_name!r} -> {target_name!r}"
        )

    return LearnedAlias(
        alias=source_name,
        target=target_name,
        reason=reason,
        confidence=1.0,
    )


def resolve_fixture_cache_first(
    multi: MultiSourceFixture,
    fixtures: Sequence[CanonicalFixture],
    *,
    verified_aliases: Mapping[str, str] | None = None,
    competition_aliases: Mapping[str, str] | None = None,
    fixture_index: Mapping[
        tuple[str, str, str], Sequence[CanonicalFixture]
    ] | None = None,
    time_index: Mapping[
        tuple[str, str], Sequence[CanonicalFixture]
    ] | None = None,
    pair_similarity_floor: float = 55.0,
    winner_margin: float = 8.0,
    orientation_margin: float = 8.0,
) -> FixtureResolveResult:
    """Fast alias lookup first; deterministic fixture resolution only on misses.

    Hot path:
      source team -> dict alias lookup -> exact fixture identity.

    Cold path:
      exact date + exact normalized kickoff + league -> tiny fixture bucket.
      If one fixture remains, learn missing aliases.
      If several remain, compare home/away only inside that bucket and learn only
      when one pair is clearly unique.

    This deliberately avoids global fuzzy scans.
    """

    aliases = dict(verified_aliases or {})
    our_names = {
        name
        for f in fixtures
        for name in (f.forebet_home, f.forebet_away)
    }

    home_target, home_status = resolve_verified_alias(
        multi.github_forebet_home,
        known_our_forebet_names=our_names,
        verified_aliases=aliases,
    )
    away_target, away_status = resolve_verified_alias(
        multi.github_forebet_away,
        known_our_forebet_names=our_names,
        verified_aliases=aliases,
    )

    if "CONFLICT" in home_status or "CONFLICT" in away_status:
        return FixtureResolveResult(
            FixtureResolveStatus.CONFLICT,
            None,
            reason="ALIAS_CONFLICT",
        )

    if multi.github_forebet_competition:
        index = (
            fixture_index
            if fixture_index is not None
            else build_fixture_index(
                fixtures,
                competition_aliases=competition_aliases,
            )
        )
        key = _coarse_key(
            multi.kickoff,
            multi.github_forebet_competition,
            competition_aliases,
        )
        candidates = list(index.get(key, ()))
        bucket_reason = "DATE_TIME_LEAGUE"
    else:
        fallback = (
            time_index
            if time_index is not None
            else build_time_index(fixtures)
        )
        key2 = (
            multi.kickoff.date().isoformat(),
            _time_key(multi.kickoff),
        )
        candidates = list(fallback.get(key2, ()))
        bucket_reason = "DATE_TIME"

    # Fast path: both team names already resolved by exact name / alias dictionary.
    if home_target is not None and away_target is not None:
        exact = [
            f for f in candidates
            if f.forebet_home == home_target and f.forebet_away == away_target
        ]
        if len(exact) == 1:
            return FixtureResolveResult(
                FixtureResolveStatus.FAST_ALIAS,
                exact[0],
                candidate_count=len(candidates),
                reason="ALIAS_CACHE_HIT",
            )
        if len(exact) > 1:
            return FixtureResolveResult(
                FixtureResolveStatus.AMBIGUOUS,
                None,
                candidate_count=len(exact),
                reason="DUPLICATE_EXACT_FIXTURE",
            )

    if not candidates:
        return FixtureResolveResult(
            FixtureResolveStatus.NO_FIXTURE,
            None,
            candidate_count=0,
            reason=f"NO_{bucket_reason}_BUCKET",
        )

    # Cold path A: date + exact time + league already identify one fixture.
    if len(candidates) == 1:
        fixture = candidates[0]

        orientation_error = _orientation_conflict(
            multi,
            fixture,
            home_target=home_target,
            away_target=away_target,
            orientation_margin=orientation_margin,
        )
        if orientation_error:
            return FixtureResolveResult(
                FixtureResolveStatus.CONFLICT,
                None,
                candidate_count=1,
                reason=orientation_error,
            )

        if (
            classify_team(multi.github_forebet_home)
            != classify_team(fixture.forebet_home)
            or classify_team(multi.github_forebet_away)
            != classify_team(fixture.forebet_away)
        ):
            return FixtureResolveResult(
                FixtureResolveStatus.CONFLICT,
                None,
                candidate_count=1,
                reason="TEAM_CLASS_MISMATCH",
            )

        learned: list[LearnedAlias] = []
        try:
            for source_name, target_name in (
                (multi.github_forebet_home, fixture.forebet_home),
                (multi.github_forebet_away, fixture.forebet_away),
            ):
                row = _learn_if_needed(
                    source_name,
                    target_name,
                    existing_aliases=aliases,
                    reason=f"UNIQUE_{bucket_reason}_FIXTURE",
                )
                if row:
                    learned.append(row)
        except ValueError as exc:
            return FixtureResolveResult(
                FixtureResolveStatus.CONFLICT,
                None,
                candidate_count=1,
                reason=str(exc),
            )

        return FixtureResolveResult(
            FixtureResolveStatus.DETERMINISTIC_UNIQUE,
            fixture,
            learned_aliases=tuple(learned),
            candidate_count=1,
            reason=f"UNIQUE_{bucket_reason}_FIXTURE",
        )

    # Cold path B: same league often has several simultaneous fixtures.
    # Compare only this small bucket, never the global team universe.
    ranked: list[tuple[float, float, float, CanonicalFixture]] = []
    for fixture in candidates:
        if (
            classify_team(multi.github_forebet_home)
            != classify_team(fixture.forebet_home)
            or classify_team(multi.github_forebet_away)
            != classify_team(fixture.forebet_away)
        ):
            continue

        orientation_error = _orientation_conflict(
            multi,
            fixture,
            home_target=home_target,
            away_target=away_target,
            orientation_margin=orientation_margin,
        )
        if orientation_error:
            continue

        hs = _ratio(multi.github_forebet_home, fixture.forebet_home)
        aws = _ratio(multi.github_forebet_away, fixture.forebet_away)
        if hs < pair_similarity_floor or aws < pair_similarity_floor:
            continue
        ranked.append(((hs + aws) / 2.0, hs, aws, fixture))

    ranked.sort(key=lambda x: x[0], reverse=True)

    if not ranked:
        return FixtureResolveResult(
            FixtureResolveStatus.AMBIGUOUS,
            None,
            candidate_count=len(candidates),
            reason="NO_COMPATIBLE_TEAM_PAIR_IN_BUCKET",
        )

    best = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else -1.0
    if len(ranked) > 1 and best[0] - second_score < winner_margin:
        return FixtureResolveResult(
            FixtureResolveStatus.AMBIGUOUS,
            None,
            candidate_count=len(candidates),
            reason="TEAM_PAIR_NOT_UNIQUE_ENOUGH",
        )

    fixture = best[3]
    learned: list[LearnedAlias] = []
    try:
        for source_name, target_name in (
            (multi.github_forebet_home, fixture.forebet_home),
            (multi.github_forebet_away, fixture.forebet_away),
        ):
            row = _learn_if_needed(
                source_name,
                target_name,
                existing_aliases=aliases,
                reason=f"UNIQUE_TEAM_PAIR_WITHIN_{bucket_reason}",
            )
            if row:
                learned.append(row)
    except ValueError as exc:
        return FixtureResolveResult(
            FixtureResolveStatus.CONFLICT,
            None,
            candidate_count=len(candidates),
            reason=str(exc),
        )

    return FixtureResolveResult(
        FixtureResolveStatus.DETERMINISTIC_TEAM_PAIR,
        fixture,
        learned_aliases=tuple(learned),
        candidate_count=len(candidates),
        reason=(
            f"UNIQUE_TEAM_PAIR_WITHIN_{bucket_reason}:"
            f"{best[1]:.1f}/{best[2]:.1f}"
        ),
    )
