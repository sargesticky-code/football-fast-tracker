# Fast Tracker → Supabase migration

This branch moves Fast Tracker from a spreadsheet-centric architecture to a PostgreSQL-first architecture without breaking the current Google Sheet.

## Safety rule

The existing Google Sheet and GitHub production feeds remain the source during migration. Do **not** cut over until row counts and sample fixtures match.

## Stage 1 — create the database

Run:

`supabase/migrations/001_core_schema.sql`

in the target Supabase project.

The schema is deliberately standard PostgreSQL. Supabase is the current host, not a permanent lock-in.

## Stage 2 — import the current production feeds

Set two secrets in the runtime that executes the sync:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Then run:

```bash
python scripts/supabase_sync.py
```

The script imports:

- `data/hkjc_current.csv` → `matches` + `hkjc_odds_current`
- `data/forebet_current.csv` → `forebet_predictions`
- `data/model_current.csv` → `model_predictions`
- `data/team_alias_registry.csv` → `team_aliases`

All joins use HKJC `FBxxxx` as the canonical fixture key.

## Stage 3 — live data

The existing Google Sheet `LiveStatsHistory` is migrated separately into:

- `live_stats_current` — one current row per fixture
- `live_stats_history` — optional historical snapshots

Do not store every redundant refresh forever. Keep current state in `live_stats_current`; history should be retained only when it is useful for analysis.

## Stage 4 — dashboard

The web/mobile dashboard should read from:

`fast_tracker_live_v`

Google Sheets then becomes an admin / QA / manual-alias surface instead of the primary application database.

## Cutover checks

Before switching the dashboard, verify for the same active HKJC horizon:

1. HKJC fixture count
2. selling HAD fixture count
3. Forebet matched count
4. alias count and manual overrides
5. model coverage / quality
6. live fixture count
7. sample FB ids match field-for-field
8. stale/failed source states remain fail-closed

Only after those checks pass should Sheet formulas stop being production-critical.
