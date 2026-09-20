from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from multibetter.aliasing.registry import resolve_verified_alias


class BridgeStatus(str, Enum):
    EXACT = "EXACT"
    ALIAS = "ALIAS"
    CANDIDATE = "CANDIDATE"
    OUR_REFERENCE_MISSING = "OUR_REFERENCE_MISSING"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class TeamBridgeResult:
    source_name: str
    status: BridgeStatus
    our_forebet_name: str | None = None
    reason: str = ""


def bridge_team_name(
    github_forebet_name: str,
    our_forebet_names: Iterable[str],
    *,
    exception_aliases: Mapping[str, str] | None = None,
) -> TeamBridgeResult:
    """Exact-first GitHub-Forebet -> OUR-Forebet bridge.

    Production accepts only:
    - exact Forebet identity, or
    - a verified static exception alias.

    Normalized/fuzzy similarities are candidates only and cannot silently enter
    production.
    """

    target, status = resolve_verified_alias(
        github_forebet_name,
        known_our_forebet_names=our_forebet_names,
        verified_aliases=exception_aliases or {},
    )

    if status == "EXACT":
        return TeamBridgeResult(
            github_forebet_name,
            BridgeStatus.EXACT,
            target,
            status,
        )

    if status == "VERIFIED_ALIAS":
        return TeamBridgeResult(
            github_forebet_name,
            BridgeStatus.ALIAS,
            target,
            status,
        )

    if status == "CANDIDATE_NORMALIZED_EQUALITY":
        return TeamBridgeResult(
            github_forebet_name,
            BridgeStatus.CANDIDATE,
            None,
            status,
        )

    if "CONFLICT" in status:
        return TeamBridgeResult(
            github_forebet_name,
            BridgeStatus.CONFLICT,
            None,
            status,
        )

    return TeamBridgeResult(
        github_forebet_name,
        BridgeStatus.OUR_REFERENCE_MISSING,
        None,
        status,
    )
