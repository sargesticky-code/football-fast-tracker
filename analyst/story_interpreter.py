"""Grounded professional story layer for Fast Tracker.

The betting candidate and every numeric fact come from Supabase
app-match-analysis.  PydanticAI is allowed to improve explanation and
storytelling only; it must not change the evidence or invent facts.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent


DEFAULT_SUPABASE_URL = "https://hekqxhgjexzxnecwhyao.supabase.co"


class ProfessionalStory(BaseModel):
    headline: str = Field(description="Short professional match-analysis headline.")
    executive_summary: str = Field(description="2-4 sentence evidence-led match summary.")
    match_story: str = Field(description="Readable narrative explaining how the match is expected to develop.")
    market_interpretation: str = Field(description="Explain price versus model probability without changing any number.")
    betting_view: str = Field(description="Repeat the deterministic action/selection/odds/edge faithfully, with reasons.")
    human_factors: str = Field(description="Explain confirmed Phase 2 evidence; distinguish confirmed from pending.")
    live_interpretation: str = Field(description="Explain Phase 3 evidence if live; otherwise say it is not available yet.")
    risk_and_invalidators: list[str] = Field(description="Concrete reasons the view can fail or should be downgraded.")
    cantonese_voiceover: str = Field(description="Natural professional Cantonese narration suitable for a football video.")


INSTRUCTIONS = """You are the narrative/explainability layer for Fast Tracker football analytics.

NON-NEGOTIABLE:
1. The supplied JSON is the only factual source.
2. Never alter odds, probabilities, edge, score, minute, injuries, lineup state, source coverage, or model outputs.
3. Never invent players, news, tactics, injuries, motivation, weather or market movement.
4. The deterministic decision.action is authoritative. Do not upgrade WATCH/PASS/NO_BET into a bet.
5. A candidate edge is not the same as a validated profitable edge. State calibration limitations when present.
6. Distinguish: most likely outcome vs best value relative to market price.
7. Explain disagreement between evidence families instead of hiding it.
8. Professional betting language: probability, price, edge, uncertainty, invalidation. No guaranteed-win language.
9. Cantonese output should sound like a professional football analyst, not a sales pitch.
10. If data is missing, say exactly which layer is missing rather than filling gaps.

Return only the structured output schema.
"""


def fetch_grounded_analysis(match_id: str, base_url: str | None = None) -> dict[str, Any]:
    base = (base_url or os.getenv("FT_SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
    query = urllib.parse.urlencode({"id": match_id})
    url = f"{base}/functions/v1/app-match-analysis?{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError(f"Supabase interpreter error: {payload['error']}")
    return payload


def deterministic_story(payload: dict[str, Any]) -> ProfessionalStory:
    story = payload.get("story") or {}
    decision = payload.get("decision") or {}
    invalidators = list(payload.get("invalidators") or [])
    return ProfessionalStory(
        headline=story.get("headline") or "Fast Tracker match interpretation",
        executive_summary=story.get("summary") or "Insufficient grounded evidence.",
        match_story=" ".join(
            x for x in [
                story.get("modelRead"),
                story.get("humanRead"),
                story.get("liveRead"),
                story.get("movementRead"),
            ] if x
        ),
        market_interpretation=story.get("marketRead") or "Market comparison unavailable.",
        betting_view=story.get("advice") or f"Action: {decision.get('action', 'WATCH')}",
        human_factors=story.get("humanRead") or "Phase 2 evidence unavailable.",
        live_interpretation=story.get("liveRead") or "Phase 3 live evidence unavailable.",
        risk_and_invalidators=invalidators or [story.get("riskRead") or "No additional risk flag recorded."],
        cantonese_voiceover=(
            (story.get("headline") or "") + "。"
            + (story.get("summary") or "") + " "
            + (story.get("advice") or "")
        ).strip(),
    )


def build_agent() -> Agent[None, ProfessionalStory] | None:
    model = os.getenv("FT_ANALYST_MODEL", "").strip()
    if not model:
        return None
    return Agent(
        model,
        output_type=ProfessionalStory,
        instructions=INSTRUCTIONS,
    )


def narrate(payload: dict[str, Any]) -> ProfessionalStory:
    agent = build_agent()
    if agent is None:
        return deterministic_story(payload)

    frozen = {
        "match": payload.get("match"),
        "decision": payload.get("decision"),
        "story": payload.get("story"),
        "evidence": payload.get("evidence"),
        "invalidators": payload.get("invalidators"),
        "phaseCoverage": payload.get("phaseCoverage"),
        "governance": payload.get("governance"),
        "engine": payload.get("engine"),
        "generatedAt": payload.get("generatedAt"),
    }
    prompt = (
        "Turn this already-calculated Fast Tracker evidence into a professional, coherent match story. "
        "Preserve every numeric fact and obey the deterministic betting action.\n\n"
        + json.dumps(frozen, ensure_ascii=False, separators=(",", ":"))
    )
    result = agent.run_sync(prompt)
    return result.output


def interpret_match(match_id: str) -> dict[str, Any]:
    payload = fetch_grounded_analysis(match_id)
    story = narrate(payload)
    return {
        "match_id": match_id,
        "grounded_engine": payload.get("engine"),
        "narrator": os.getenv("FT_ANALYST_MODEL") or "deterministic-fallback",
        "decision": payload.get("decision"),
        "story": story.model_dump(),
        "phaseCoverage": payload.get("phaseCoverage"),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m analyst.story_interpreter <HKJC_EVENT_ID>")
    print(json.dumps(interpret_match(sys.argv[1]), ensure_ascii=False, indent=2))
