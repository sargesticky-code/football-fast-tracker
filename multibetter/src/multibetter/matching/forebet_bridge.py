from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from multibetter.normalization.teams import normalize_text


class BridgeStatus(str, Enum):
    EXACT = "EXACT"
    ALIAS = "ALIAS"
    OUR_REFERENCE_MISSING = "OUR_REFERENCE_MISSING"
    MISMATCH = "MISMATCH"


@dataclass(frozen=True)
class TeamBridgeResult:
    source_name: str
    status: BridgeStatus
    our_forebet_name: str | None = None


def bridge_team_name(
    github_forebet_name: str,
    our_forebet_names: Iterable[str],
    *,
    exception_aliases: Mapping[str, str] | None = None,
) -> TeamBridgeResult:
    """Exact-first GitHub-Forebet -> OUR-Forebet bridge.

    This is deliberately not a fuzzy matcher. Both systems read Forebet names, so
    exact identity is expected. Aliases are reserved for verified exceptions.
    """

    ours = set(our_forebet_names)
    if github_forebet_name in ours:
        return TeamBridgeResult(
            github_forebet_name,
            BridgeStatus.EXACT,
            github_forebet_name,
        )

    if exception_aliases and github_forebet_name in exception_aliases:
        target = exception_aliases[github_forebet_name]
        if target in ours:
            return TeamBridgeResult(
                github_forebet_name,
                BridgeStatus.ALIAS,
                target,
            )

    # A normalized equality is diagnostic only, not automatically accepted.
    source_norm = normalize_text(github_forebet_name)
    for name in ours:
        if normalize_text(name) == source_norm:
            return TeamBridgeResult(
                github_forebet_name,
                BridgeStatus.MISMATCH,
                name,
            )

    return TeamBridgeResult(
        github_forebet_name,
        BridgeStatus.OUR_REFERENCE_MISSING,
        None,
    )
