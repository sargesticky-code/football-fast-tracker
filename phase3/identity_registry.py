"""Phase 3 Layer 2: persistent external live-match identity registry.

This module is deliberately independent from Phase 1 value logic and Phase 2
human factors. It promotes an HKJC event -> external match ID only after
repeated, fixture-consistent observations. Ambiguity fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Iterable

PROMOTE_CONFIDENCE = 0.85
PROMOTE_OBSERVATIONS = 3


def _s(v) -> str:
    return "" if v is None else str(v).strip()


@dataclass(frozen=True)
class IdentityObservation:
    hkjc_event_id: str
    source: str
    source_match_id: str
    confidence: float
    observed_at: str
    home: str = ""
    away: str = ""
    kickoff: str = ""
    competition: str = ""

    def normalized(self) -> "IdentityObservation":
        return IdentityObservation(
            hkjc_event_id=_s(self.hkjc_event_id),
            source=_s(self.source).upper(),
            source_match_id=_s(self.source_match_id),
            confidence=max(0.0, min(1.0, float(self.confidence))),
            observed_at=_s(self.observed_at) or datetime.now(timezone.utc).isoformat(),
            home=_s(self.home),
            away=_s(self.away),
            kickoff=_s(self.kickoff),
            competition=_s(self.competition),
        )


def _fixture_signature(o: IdentityObservation) -> tuple[str, str, str]:
    return (o.home.casefold(), o.away.casefold(), o.kickoff)


def rebuild_registry(observations: Iterable[IdentityObservation]) -> list[dict]:
    """Rebuild deterministic candidate/verified state from append-only evidence."""
    obs = [x.normalized() for x in observations]
    groups: dict[tuple[str, str, str], list[IdentityObservation]] = {}
    source_id_owners: dict[tuple[str, str], set[str]] = {}

    for o in obs:
        if not (o.hkjc_event_id and o.source and o.source_match_id):
            continue
        groups.setdefault((o.hkjc_event_id, o.source, o.source_match_id), []).append(o)
        source_id_owners.setdefault((o.source, o.source_match_id), set()).add(o.hkjc_event_id)

    rows: list[dict] = []
    for key, evidence in sorted(groups.items()):
        event_id, source, source_match_id = key
        signatures = {_fixture_signature(x) for x in evidence}
        competing_ids = {
            k[2] for k in groups
            if k[0] == event_id and k[1] == source and k[2] != source_match_id
        }
        collision = len(source_id_owners[(source, source_match_id)]) > 1
        conflict = len(signatures) > 1 or bool(competing_ids) or collision
        evidence_count = len({x.observed_at for x in evidence})
        confidence = min(x.confidence for x in evidence)
        verified = (
            not conflict
            and confidence >= PROMOTE_CONFIDENCE
            and evidence_count >= PROMOTE_OBSERVATIONS
        )
        latest = max(evidence, key=lambda x: x.observed_at)

        rows.append({
            "hkjc_event_id": event_id,
            "source": source,
            "source_match_id": source_match_id,
            "status": "VERIFIED" if verified else ("CONFLICT" if conflict else "CANDIDATE"),
            "confidence": round(confidence, 3),
            "evidence_count": evidence_count,
            "conflict": conflict,
            "competing_ids": sorted(competing_ids),
            "last_observed_at": latest.observed_at,
            "home": latest.home,
            "away": latest.away,
            "kickoff": latest.kickoff,
            "competition": latest.competition,
        })
    return rows


def usable_mapping(registry: Iterable[dict], hkjc_event_id: str, source: str) -> dict | None:
    rows = [
        r for r in registry
        if r.get("hkjc_event_id") == hkjc_event_id
        and r.get("source") == source.upper()
        and r.get("status") == "VERIFIED"
    ]
    return rows[0] if len(rows) == 1 else None


def observation_to_dict(o: IdentityObservation) -> dict:
    return asdict(o.normalized())
