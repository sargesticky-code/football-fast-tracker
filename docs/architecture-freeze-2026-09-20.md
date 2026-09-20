# Fast Tracker 2026 — Architecture Freeze

Frozen: 2026-09-20

## Product definition

> **Fast Tracker 2026 is a SQL-first football betting intelligence platform. HKJC defines the active betting universe. External prediction models, market information and historical statistics provide independent evidence. Phase 1 handles pre-match intelligence; Phase 2 introduces human/context factors; Phase 3 adds time-series live intelligence.**

**Multibetter is no longer a separate product name.** Existing branch/path names remain temporarily as legacy technical identifiers so current collection jobs are not broken.

Its role inside Fast Tracker is:

> **Multi-source Intelligence Layer**

## Authority hierarchy

1. HKJC defines the active/bettable fixture universe and canonical `FBxxxx` event identity.
2. HKJC names remain canonical display identity.
3. Forebet, the Multi-source Intelligence Layer, statistical models and external market benchmarks are evidence, not fixture authority.
4. Data quality failures must fail closed. A failed refresh must not overwrite a valid last-known-good evidence row with empty data.

## Database boundary

### Ingest / compatibility

Existing `public.*` tables remain in place while migration is active. Existing GitHub feeds and the existing Google Sheet are not cut over or modified by the canonical-core installation.

### Internal canonical core

Internal normalized data lives in the non-app-facing `private` schema.

Phase 1 core:
- `private.matches`
- `private.market_current`
- `private.source_registry`
- `private.prediction_evidence_current`
- `private.multisource_consensus_current`
- `private.phase1_decision_current`

Reserved extension points:
- Phase 2: `private.match_factors_current`
- Phase 3: `private.live_event_timeline`

### App contract

The `api` schema is an explicit contract layer. It is **not automatically public**.

Current internal Phase 1 contract:
- `api.phase1_match_intelligence_v`

Frontend exposure must use explicit grants + RLS/access policy. Do not expose the entire betting database.

## Multi-source migration

Legacy source:
- GitHub branch: `multibetter-v1`
- Current output: `multibetter/data/multibetter_current.csv`

The source already resolves fixtures to HKJC `FBxxxx`, so canonical ingestion uses `hkjc_event_id` directly instead of rebuilding global fuzzy matching.

The production Supabase sync now treats the file as the **Multi-source Intelligence Layer**, preserves last-known-good rows on source failure, and refreshes canonical evidence after successful staging sync.

## Phase separation

### Phase 1 — pre-match intelligence

Combine, without conflating:
- HKJC market price / implied probability
- Forebet
- Multi-source consensus
- Dixon-Coles
- Pi ratings
- form model
- external market benchmarks
- historical/model evaluation

The final decision engine is stored separately from raw evidence. Do not invent decision thresholds merely because evidence exists.

### Phase 2 — human/context factors

Add lineup, injury, rest, travel, motivation, rotation, weather/pitch and referee signals as structured factors. Human/context factors should be able to confirm or contradict Phase 1 rather than overwrite raw evidence.

### Phase 3 — live intelligence

Use time-series/event intelligence. Do not indefinitely store redundant full snapshots every five minutes as the primary live model. Prefer current state plus meaningful sparse events/changes and derived time-series features.

## Safety / migration rules

- Do not modify or cut over the existing Google Sheet until validation is complete.
- Do not rename/drop existing production tables merely to fit the new design.
- Migrate additively and validate row counts plus sample `FBxxxx` field-by-field.
- Internal schemas stay inaccessible to `anon` and `authenticated` by default.
- App-facing access must be explicitly designed; it is not inherited automatically from internal storage.
