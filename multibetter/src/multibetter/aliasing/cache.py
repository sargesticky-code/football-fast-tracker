from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from multibetter.matching.fixture_resolver import LearnedAlias


@dataclass(frozen=True)
class AliasCacheRow:
    alias: str
    target: str
    status: str = "AUTO_DETERMINISTIC"
    confidence: float = 1.0
    first_seen: str = ""
    last_seen: str = ""
    observation_count: int = 1
    note: str = ""


def merge_learned_aliases(
    existing: Iterable[AliasCacheRow],
    learned: Iterable[LearnedAlias],
    *,
    observed_at: datetime,
) -> tuple[AliasCacheRow, ...]:
    """Persist deterministic one-time learning into the fast alias cache."""

    state = {row.alias: row for row in existing}
    stamp = observed_at.isoformat()

    for item in learned:
        current = state.get(item.alias)
        if current is not None:
            if current.target != item.target:
                raise ValueError(
                    f"Alias conflict: {item.alias!r} -> {current.target!r} "
                    f"vs {item.target!r}"
                )
            state[item.alias] = AliasCacheRow(
                alias=current.alias,
                target=current.target,
                status=current.status,
                confidence=max(current.confidence, item.confidence),
                first_seen=current.first_seen or stamp,
                last_seen=stamp,
                observation_count=current.observation_count + 1,
                note=current.note or item.reason,
            )
            continue

        state[item.alias] = AliasCacheRow(
            alias=item.alias,
            target=item.target,
            status="AUTO_DETERMINISTIC",
            confidence=item.confidence,
            first_seen=stamp,
            last_seen=stamp,
            observation_count=1,
            note=item.reason,
        )

    return tuple(sorted(state.values(), key=lambda x: x.alias.lower()))


def touch_aliases(
    existing: Iterable[AliasCacheRow],
    aliases_used: Iterable[str],
    *,
    observed_at: datetime,
) -> tuple[AliasCacheRow, ...]:
    """Update usage metadata for aliases that resolved through the fast path."""

    used = set(aliases_used)
    stamp = observed_at.isoformat()
    rows: list[AliasCacheRow] = []

    for row in existing:
        if row.alias not in used:
            rows.append(row)
            continue
        rows.append(
            AliasCacheRow(
                alias=row.alias,
                target=row.target,
                status=row.status,
                confidence=row.confidence,
                first_seen=row.first_seen or stamp,
                last_seen=stamp,
                observation_count=row.observation_count + 1,
                note=row.note,
            )
        )

    return tuple(sorted(rows, key=lambda x: x.alias.lower()))
