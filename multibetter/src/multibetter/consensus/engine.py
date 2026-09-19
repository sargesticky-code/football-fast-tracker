from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from multibetter.models import Market


@dataclass(frozen=True)
class ConsensusResult:
    market: Market
    probabilities: dict[str, float]
    sources_used: tuple[str, ...]
    total_weight: float


def weighted_consensus(
    rows: Iterable[tuple[str, Mapping[str, float], float]],
    *,
    market: Market,
    source_weights: Mapping[tuple[str, Market], float],
    min_match_confidence: float = 0.85,
) -> ConsensusResult:
    """Combine already-matched predictions with source+market specific weights.

    rows: (source, probabilities, match_confidence)
    """
    numerators: dict[str, float] = {}
    total_weight = 0.0
    used: list[str] = []

    for source, probs, match_confidence in rows:
        if match_confidence < min_match_confidence:
            continue
        weight = float(source_weights.get((source, market), 0.0))
        if weight <= 0 or not probs:
            continue

        clean = {k: float(v) for k, v in probs.items() if v is not None}
        if not clean:
            continue

        scale = sum(clean.values())
        if scale <= 0:
            continue
        if scale > 1.5:
            clean = {k: v / 100.0 for k, v in clean.items()}

        total = sum(clean.values())
        clean = {k: v / total for k, v in clean.items()}

        for key, value in clean.items():
            numerators[key] = numerators.get(key, 0.0) + value * weight
        total_weight += weight
        used.append(source)

    if total_weight == 0:
        return ConsensusResult(market, {}, tuple(), 0.0)

    return ConsensusResult(
        market=market,
        probabilities={k: round(v / total_weight, 6) for k, v in numerators.items()},
        sources_used=tuple(used),
        total_weight=round(total_weight, 6),
    )
