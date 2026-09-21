"""Phase 3 Layer 2: persistent external live-match identity registry.

Independent from Phase 1 value logic and Phase 2 human factors. New mappings
must earn repeated evidence. Once verified, a mapping is terminal/locked and
is reused instead of fuzzy-rematching; contradictory later evidence is
quarantined and makes lookup fail closed until reviewed.
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
            home=_s(self.home), away=_s(self.away), kickoff=_s(self.kickoff),
            competition=_s(self.competition),
        )


def _fixture_signature(o: IdentityObservation) -> tuple[str, str, str]:
    return (o.home.casefold(), o.away.casefold(), o.kickoff)


def observation_key(o: IdentityObservation) -> tuple[str, str, str, str]:
    """Stable key preventing retries/restores from inflating promotion evidence."""
    n = o.normalized()
    return (n.hkjc_event_id, n.source, n.source_match_id, n.observed_at)


def dedupe_observations(observations: Iterable[IdentityObservation]) -> list[IdentityObservation]:
    """Deduplicate exact observation identities while preserving first-seen order."""
    out: list[IdentityObservation] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw in observations:
        o = raw.normalized()
        key = observation_key(o)
        if key in seen:
            continue
        seen.add(key)
        out.append(o)
    return out


def rebuild_registry(observations: Iterable[IdentityObservation]) -> list[dict]:
    """Build deterministic candidate/verified state from append-only evidence."""
    obs = dedupe_observations(observations)
    groups: dict[tuple[str, str, str], list[IdentityObservation]] = {}
    owners: dict[tuple[str, str], set[str]] = {}
    for o in obs:
        if not (o.hkjc_event_id and o.source and o.source_match_id):
            continue
        groups.setdefault((o.hkjc_event_id, o.source, o.source_match_id), []).append(o)
        owners.setdefault((o.source, o.source_match_id), set()).add(o.hkjc_event_id)

    rows: list[dict] = []
    for (event_id, source, source_match_id), evidence in sorted(groups.items()):
        signatures = {_fixture_signature(x) for x in evidence}
        competing = {k[2] for k in groups if k[0] == event_id and k[1] == source and k[2] != source_match_id}
        conflict = len(signatures) > 1 or bool(competing) or len(owners[(source, source_match_id)]) > 1
        evidence_count = len({x.observed_at for x in evidence})
        confidence = min(x.confidence for x in evidence)
        verified = not conflict and confidence >= PROMOTE_CONFIDENCE and evidence_count >= PROMOTE_OBSERVATIONS
        latest = max(evidence, key=lambda x: x.observed_at)
        rows.append({
            "hkjc_event_id": event_id, "source": source, "source_match_id": source_match_id,
            "status": "VERIFIED" if verified else ("CONFLICT" if conflict else "CANDIDATE"),
            "confidence": round(confidence, 3), "evidence_count": evidence_count,
            "conflict": conflict, "competing_ids": sorted(competing),
            "last_observed_at": latest.observed_at, "home": latest.home, "away": latest.away,
            "kickoff": latest.kickoff, "competition": latest.competition,
            "terminal": verified,
        })
    return rows


def merge_terminal_registry(previous: Iterable[dict], rebuilt: Iterable[dict]) -> list[dict]:
    """Retain verified mappings across cycles; quarantine contradictory evidence."""
    old = [dict(r) for r in previous]
    new = [dict(r) for r in rebuilt]
    locked = {(r.get("hkjc_event_id"), r.get("source")): r for r in old if r.get("status") in {"VERIFIED", "LOCKED_CONFLICT"}}
    new_by_key: dict[tuple[str, str], list[dict]] = {}
    for r in new:
        new_by_key.setdefault((r.get("hkjc_event_id"), r.get("source")), []).append(r)

    output: list[dict] = []
    consumed: set[tuple[str, str]] = set()
    for key, prior in locked.items():
        candidates = new_by_key.get(key, [])
        contradiction = any(r.get("source_match_id") != prior.get("source_match_id") or r.get("status") == "CONFLICT" for r in candidates)
        kept = dict(prior)
        kept["terminal"] = True
        if contradiction:
            kept["status"] = "LOCKED_CONFLICT"
            kept["conflict"] = True
            kept["quarantined_ids"] = sorted({str(r.get("source_match_id")) for r in candidates if r.get("source_match_id") != prior.get("source_match_id")})
        output.append(kept)
        consumed.add(key)

    for r in new:
        key = (r.get("hkjc_event_id"), r.get("source"))
        if key not in consumed:
            output.append(r)
    return sorted(output, key=lambda r: (str(r.get("hkjc_event_id")), str(r.get("source")), str(r.get("source_match_id"))))


def usable_mapping(registry: Iterable[dict], hkjc_event_id: str, source: str) -> dict | None:
    rows = [r for r in registry if r.get("hkjc_event_id") == hkjc_event_id and r.get("source") == source.upper() and r.get("status") == "VERIFIED"]
    return rows[0] if len(rows) == 1 else None


def observation_to_dict(o: IdentityObservation) -> dict:
    return asdict(o.normalized())
