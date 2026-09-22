# Fast Tracker Analyst

Grounded narration layer for the Supabase Fast Tracker platform.

## Architecture

1. Supabase `app-match-analysis` calculates market probabilities, evidence-family consensus, candidate edge, Phase 2/3/4 context, invalidators and the authoritative action.
2. `story_interpreter.py` fetches that JSON.
3. PydanticAI may improve the professional narrative **only**. It may not change any number or upgrade the deterministic action.
4. Without an LLM provider credential the module falls back to the grounded deterministic story, so the pipeline remains functional.

## Runtime

Pinned dependency:

```
pydantic-ai-slim[openai,google]==2.46.0
```

Optional environment variables:

- `FT_SUPABASE_URL` — defaults to the Fast Tracker Supabase project URL.
- `FT_ANALYST_MODEL` — PydanticAI model string. Leave unset for deterministic fallback.
- Provider credential required by the selected PydanticAI model.

Run:

```bash
python -m analyst.story_interpreter FB5644
```

## Governance

- Supabase is the source of truth.
- HKJC price and model probabilities are immutable inputs to the narrator.
- Missing evidence is reported, never invented.
- Candidate value is not promoted to a production Best Bet while calibration remains pending.
- Automated staking remains disabled until Phase 5 calibration and Phase 7 risk controls are validated.
