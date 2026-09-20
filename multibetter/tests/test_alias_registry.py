from datetime import datetime

import pytest

from multibetter.aliasing.registry import (
    AliasCandidate,
    AliasStatus,
    VerifiedAlias,
    add_candidate_observation,
    audit_alias_state,
    resolve_verified_alias,
    verified_map,
)


def test_exact_beats_alias_table():
    target, status = resolve_verified_alias(
        "Manchester City",
        known_our_forebet_names={"Manchester City"},
        verified_aliases={"Manchester City": "Wrong Target"},
    )
    assert target == "Manchester City"
    assert status == "EXACT"


def test_verified_alias_is_allowed():
    target, status = resolve_verified_alias(
        "St Gallen",
        known_our_forebet_names={"St. Gallen"},
        verified_aliases={"St Gallen": "St. Gallen"},
    )
    assert target == "St. Gallen"
    assert status == "VERIFIED_ALIAS"


def test_normalized_equality_is_candidate_not_auto_match():
    target, status = resolve_verified_alias(
        "Atlético Madrid",
        known_our_forebet_names={"Atletico Madrid"},
        verified_aliases={},
    )
    assert target is None
    assert status == "CANDIDATE_NORMALIZED_EQUALITY"


def test_candidate_needs_repeated_context_before_review_ready():
    t1 = datetime(2026, 9, 20, 8, 0)
    row = add_candidate_observation(
        None,
        alias="Liverpool (URU)",
        target="Liverpool Montevideo",
        observed_at=t1,
        similarity=90.0,
        opponent="Ind Medellin",
        event_id="A",
    )
    assert row.status == AliasStatus.CANDIDATE

    row = add_candidate_observation(
        row,
        alias="Liverpool (URU)",
        target="Liverpool Montevideo",
        observed_at=datetime(2026, 9, 21, 8, 0),
        similarity=92.0,
        opponent="Nacional",
        event_id="B",
    )
    row = add_candidate_observation(
        row,
        alias="Liverpool (URU)",
        target="Liverpool Montevideo",
        observed_at=datetime(2026, 9, 22, 8, 0),
        similarity=91.0,
        opponent="Penarol",
        event_id="C",
    )
    assert row.status == AliasStatus.REVIEW_READY


def test_team_class_mismatch_never_becomes_review_ready():
    row = add_candidate_observation(
        None,
        alias="Arsenal U21",
        target="Arsenal",
        observed_at=datetime(2026, 9, 20, 8, 0),
        similarity=99.0,
        opponent="Brighton U21",
    )
    assert row.status == AliasStatus.CONFLICT


def test_verified_alias_conflict_is_rejected():
    with pytest.raises(ValueError):
        verified_map(
            [
                VerifiedAlias("Example", "Team A"),
                VerifiedAlias("Example", "Team B"),
            ]
        )


def test_candidate_target_conflict_is_reported():
    now = datetime(2026, 9, 20, 8, 0)
    audit = audit_alias_state(
        [],
        [
            AliasCandidate("Example", "Team A", now, now),
            AliasCandidate("Example", "Team B", now, now),
        ],
    )
    assert audit.conflicts
