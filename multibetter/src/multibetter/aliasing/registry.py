from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Iterable, Mapping

from multibetter.models import TeamClass
from multibetter.normalization.teams import classify_team, normalize_text


class AliasStatus(str, Enum):
    VERIFIED = "VERIFIED"
    CANDIDATE = "CANDIDATE"
    REVIEW_READY = "REVIEW_READY"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class VerifiedAlias:
    alias: str
    target: str
    note: str = ""
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    observation_count: int = 0


@dataclass(frozen=True)
class AliasCandidate:
    alias: str
    target: str
    first_seen: datetime
    last_seen: datetime
    observation_count: int = 1
    best_similarity: float = 0.0
    latest_similarity: float = 0.0
    opponents: frozenset[str] = frozenset()
    event_ids: frozenset[str] = frozenset()
    status: AliasStatus = AliasStatus.CANDIDATE
    reason: str = ""


@dataclass(frozen=True)
class AliasAudit:
    conflicts: tuple[str, ...]
    verified_count: int
    candidate_count: int
    review_ready_count: int


def verified_map(rows: Iterable[VerifiedAlias]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        if row.alias in result and result[row.alias] != row.target:
            raise ValueError(
                f"Verified alias conflict: {row.alias!r} -> "
                f"{result[row.alias]!r} / {row.target!r}"
            )
        result[row.alias] = row.target
    return result


def evaluate_candidate(candidate: AliasCandidate) -> AliasCandidate:
    same_class = classify_team(candidate.alias) == classify_team(candidate.target)

    if not same_class:
        return replace(
            candidate,
            status=AliasStatus.CONFLICT,
            reason="TEAM_CLASS_MISMATCH",
        )

    if (
        candidate.observation_count >= 3
        and len(candidate.opponents) >= 2
        and candidate.best_similarity >= 85.0
    ):
        return replace(
            candidate,
            status=AliasStatus.REVIEW_READY,
            reason="ENOUGH_REPEATED_EVIDENCE",
        )

    return replace(
        candidate,
        status=AliasStatus.CANDIDATE,
        reason="NEEDS_MORE_EVIDENCE",
    )


def add_candidate_observation(
    existing: AliasCandidate | None,
    *,
    alias: str,
    target: str,
    observed_at: datetime,
    similarity: float,
    opponent: str | None = None,
    event_id: str | None = None,
) -> AliasCandidate:
    """Accumulate evidence without auto-promoting to a production alias."""

    similarity = max(0.0, min(float(similarity), 100.0))

    if existing is not None and (
        existing.alias != alias or existing.target != target
    ):
        raise ValueError("Observation does not match existing alias candidate pair")

    if existing is None:
        candidate = AliasCandidate(
            alias=alias,
            target=target,
            first_seen=observed_at,
            last_seen=observed_at,
            observation_count=1,
            best_similarity=similarity,
            latest_similarity=similarity,
            opponents=frozenset([opponent]) if opponent else frozenset(),
            event_ids=frozenset([event_id]) if event_id else frozenset(),
        )
    else:
        candidate = replace(
            existing,
            last_seen=max(existing.last_seen, observed_at),
            observation_count=existing.observation_count + 1,
            best_similarity=max(existing.best_similarity, similarity),
            latest_similarity=similarity,
            opponents=(
                existing.opponents | frozenset([opponent])
                if opponent
                else existing.opponents
            ),
            event_ids=(
                existing.event_ids | frozenset([event_id])
                if event_id
                else existing.event_ids
            ),
        )

    return evaluate_candidate(candidate)


def detect_target_conflicts(
    candidates: Iterable[AliasCandidate],
) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = {}
    for row in candidates:
        targets.setdefault(row.alias, set()).add(row.target)
    return {alias: vals for alias, vals in targets.items() if len(vals) > 1}


def audit_alias_state(
    verified: Iterable[VerifiedAlias],
    candidates: Iterable[AliasCandidate],
) -> AliasAudit:
    verified = tuple(verified)
    candidates = tuple(candidates)
    conflicts: list[str] = []

    try:
        verified_map(verified)
    except ValueError as exc:
        conflicts.append(str(exc))

    for alias, targets in detect_target_conflicts(candidates).items():
        conflicts.append(
            f"Candidate conflict: {alias!r} -> {sorted(targets)!r}"
        )

    verified_names = {row.alias for row in verified}
    for row in candidates:
        if row.alias in verified_names and row.status not in {
            AliasStatus.REJECTED,
            AliasStatus.CONFLICT,
        }:
            conflicts.append(
                f"Alias {row.alias!r} exists in verified and candidate sets"
            )

    return AliasAudit(
        conflicts=tuple(conflicts),
        verified_count=len(verified),
        candidate_count=len(candidates),
        review_ready_count=sum(
            1 for row in candidates if row.status == AliasStatus.REVIEW_READY
        ),
    )


def resolve_verified_alias(
    name: str,
    *,
    known_our_forebet_names: Iterable[str],
    verified_aliases: Mapping[str, str],
) -> tuple[str | None, str]:
    """Exact-first, verified-alias-second production resolver."""

    ours = set(known_our_forebet_names)

    if name in ours:
        return name, "EXACT"

    target = verified_aliases.get(name)
    if target is not None and target in ours:
        if classify_team(name) != classify_team(target):
            return None, "TEAM_CLASS_CONFLICT"
        return target, "VERIFIED_ALIAS"

    normalized = normalize_text(name)
    normalized_hits = [
        target for target in ours if normalize_text(target) == normalized
    ]
    if len(normalized_hits) == 1:
        return None, "CANDIDATE_NORMALIZED_EQUALITY"

    return None, "UNRESOLVED"
