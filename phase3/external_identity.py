"""Phase 3 Layer 2 external-board identity candidate matching.

Matching is deliberately conservative. HKJC remains the eligibility authority;
this module can only propose an external ID for an already eligible HKJC row.
Ambiguous candidates fail closed and are not written as evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
import re
import unicodedata

MIN_CONFIDENCE = 0.85
MIN_MARGIN = 0.08
MAX_KICKOFF_DRIFT_SECONDS = 45 * 60


def _norm(value: object) -> str:
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()
    tokens = re.sub(r"[^a-z0-9]+", " ", s).split()
    if tokens and tokens[-1] in {"women", "woman", "womens"}:
        tokens[-1] = "w"
    return " ".join(tokens)


def _ratio(a: object, b: object) -> float:
    aa, bb = _norm(a), _norm(b)
    return SequenceMatcher(None, aa, bb).ratio() if aa and bb else 0.0


def _ts(value: str) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Candidate:
    source_match_id: str
    confidence: float
    home: str
    away: str
    kickoff: str
    competition: str = ""
    home_score: float = 0.0
    away_score: float = 0.0
    kickoff_drift_seconds: int = 0


def score_candidate(hkjc: dict, external: dict) -> Candidate | None:
    """Score one fixture; reject reversed teams and excessive kickoff drift."""
    direct_home = _ratio(hkjc.get("home_en") or hkjc.get("home"), external.get("home"))
    direct_away = _ratio(hkjc.get("away_en") or hkjc.get("away"), external.get("away"))
    reverse_home = _ratio(hkjc.get("home_en") or hkjc.get("home"), external.get("away"))
    reverse_away = _ratio(hkjc.get("away_en") or hkjc.get("away"), external.get("home"))
    if (reverse_home + reverse_away) > (direct_home + direct_away):
        return None

    hk_ts = _ts(str(hkjc.get("kickoff_hkt") or hkjc.get("kickoff") or ""))
    ex_ts = _ts(str(external.get("kickoff") or ""))
    if hk_ts is None or ex_ts is None:
        return None
    drift = abs(hk_ts - ex_ts)
    if drift > MAX_KICKOFF_DRIFT_SECONDS:
        return None

    team_score = (direct_home + direct_away) / 2
    time_score = max(0.0, 1.0 - drift / MAX_KICKOFF_DRIFT_SECONDS)
    confidence = 0.85 * team_score + 0.15 * time_score
    return Candidate(
        source_match_id=str(external.get("id") or ""),
        confidence=round(confidence, 4),
        home=str(external.get("home") or ""),
        away=str(external.get("away") or ""),
        kickoff=str(external.get("kickoff") or ""),
        competition=str(external.get("competition") or ""),
        home_score=round(direct_home, 4),
        away_score=round(direct_away, 4),
        kickoff_drift_seconds=int(round(drift)),
    )


def ranked_candidates(hkjc: dict, external_rows: list[dict], limit: int = 3) -> list[Candidate]:
    """Return best structurally-valid candidates for diagnostics only.

    This does not relax promotion thresholds: weak/ambiguous candidates remain
    unusable. It exists so real-source gaps can be diagnosed without guessing.
    """
    scored = [c for row in external_rows if (c := score_candidate(hkjc, row)) and c.source_match_id]
    scored.sort(key=lambda c: c.confidence, reverse=True)
    return scored[:max(0, limit)]


def choose_candidate(hkjc: dict, external_rows: list[dict]) -> tuple[Candidate | None, str]:
    scored = ranked_candidates(hkjc, external_rows, limit=2)
    if not scored or scored[0].confidence < MIN_CONFIDENCE:
        return None, "NO_HIGH_CONFIDENCE_CANDIDATE"
    if len(scored) > 1 and scored[0].confidence - scored[1].confidence < MIN_MARGIN:
        return None, "AMBIGUOUS_CANDIDATES"
    return scored[0], "CANDIDATE"
