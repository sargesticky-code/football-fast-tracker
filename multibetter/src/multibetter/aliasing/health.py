from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class AliasHealth:
    total: int
    exact: int
    verified_alias: int
    unresolved: int
    conflict: int
    candidate: int = 0
    review_ready: int = 0

    @property
    def resolved_rate(self) -> float:
        return 0.0 if self.total == 0 else (self.exact + self.verified_alias) / self.total

    @property
    def exact_rate(self) -> float:
        return 0.0 if self.total == 0 else self.exact / self.total


def summarize_resolution_statuses(
    statuses: Iterable[str],
    *,
    candidate: int = 0,
    review_ready: int = 0,
) -> AliasHealth:
    values = tuple(statuses)
    return AliasHealth(
        total=len(values),
        exact=sum(1 for x in values if x == "EXACT"),
        verified_alias=sum(1 for x in values if x == "VERIFIED_ALIAS"),
        unresolved=sum(
            1 for x in values
            if x in {"UNRESOLVED", "CANDIDATE_NORMALIZED_EQUALITY"}
        ),
        conflict=sum(1 for x in values if "CONFLICT" in x),
        candidate=candidate,
        review_ready=review_ready,
    )
