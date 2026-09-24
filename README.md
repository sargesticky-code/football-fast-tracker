# Football Fast Tracker

Automated football data workers for the Supabase-first Fast Tracker app. Production data is keyed by the HKJC `FBxxxx` event id, and Supabase is the canonical serving/storage layer. The former Google Sheet dashboard is frozen legacy and is not a production target.

## Production architecture

### 1. HKJC — fixture authority and primary market

The production job talks directly to the public HKJC football GraphQL endpoint through a pinned copy of `sososo829/hkjc-football-scraper`.

It captures:

- the full current HKJC fixture list;
- official `FBxxxx` front-end ids;
- kickoff and match status;
- pools currently offered;
- current HAD home/draw/away prices.

Normalized outputs:

- `data/hkjc_current.csv` — all current/retained HKJC fixtures, including status and HAD availability;
- `data/hkjc_targets.csv` — only pre-event fixtures inside the modelling horizon with a complete, selling HAD triplet.

The previous Google-Sheet HKJC Source Snapshot is retained only as a fallback if the direct target file is missing, invalid, or stale.

### 2. Forebet — zero-credit external prediction model

Only fixtures currently bettable at HKJC are considered. `scripts/run_selective.py` fetches generic public Forebet pages through Jina's rendered-page transport, joins them to the HKJC target universe, and writes only rows with a complete 1X2 probability triplet.

Routine production:

- uses zero ScraperAPI credits;
- uses generic date and paginated prediction pages, never league-specific or event-specific exceptions;
- retries unhealthy/placeholder Jina responses with cache bypass;
- loads the permanent Forebet → HKJC alias registry before matching;
- carries forward a last-known valid model only while the same `FBxxxx` remains in the active HKJC target universe;
- restores active models from the rolling archive after a partial refresh;
- fails closed instead of replacing a valid production feed with an empty scrape.

Outputs:

- `data/forebet_current.csv`
- `data/forebet_archive.csv`
- `data/team_alias_registry.csv`

The alias registry learns only high-confidence matches. Conflicts are excluded from production matching.

### 3. Forebet O/U and corner enrichment

`scripts/enrich_forebet_markets.py` batch-fetches free rendered market pages by Forebet date and enriches already-matched `FBxxxx` rows with:

- Over/Under 2.5 prediction and probabilities;
- predicted O/U score;
- corners 9.5 prediction and probabilities;
- predicted corner score;
- average corners.

This enrichment also uses zero ScraperAPI credits and does not introduce separate league-specific routes.

### 4. Opta Power — independent global club strength

The Forebet feed is enriched with current Opta global club power ratings and confidence-matched team names. A coverage health gate prevents weak enrichment from being accepted silently.

Opta is a strength signal, not a replacement for Forebet match probabilities.

### 5. Bet365 — secondary market benchmark

Bet365 is intentionally secondary because it requires a real Chromium/Playwright session and is more fragile than HKJC GraphQL.

The job runs only when a currently bettable HKJC fixture belongs to a supported competition. Prices are matched back to the canonical HKJC `FBxxxx` id and rejected when team matching is low-confidence.

Output:

- `data/bet365_current.csv`

An empty file means there is no supported Bet365/HKJC overlap; it is not a production failure.

### 6. Dixon-Coles + Pi — independent shadow model

`penaltyblog==1.12.2` is pinned for the statistical model layer. The daily shadow model trains only from free historical results and does not use Forebet probabilities, HKJC prices, Bet365 prices, or Opta ratings as training inputs.

Coverage is fail-closed. Unsupported fixtures keep blank model probabilities rather than receiving invented values.

Output:

- `data/model_current.csv`

The shadow model remains observational until walk-forward RPS, log loss, calibration, ROI, and closing-line-value evidence justify promotion.

### 7. CatBoost / stacked ensemble — research only

The heavier research stack is manual-only. `.github/workflows/catboost_research.yml` cannot affect production feeds.

## Schedule (Hong Kong time)

- **06:45** — direct HKJC GraphQL → HKJC target gate → zero-credit Forebet/Jina → aliases → Opta → O/U/corners
- **07:05** — Dixon-Coles + Pi shadow model
- **07:15** — Bet365 benchmark when supported HKJC competitions are present
- **07:20** — freshness watchdog; dispatches the same zero-credit production workflow only when stale
- CatBoost ensemble — manual research only

## Supabase-first delivery

GitHub Actions remain useful as low-cost compute workers for Forebet, historical models and other batch enrichment, but their outputs are reconciled into Supabase. The public dashboard reads Supabase only.

Current direction:

- direct HKJC upcoming/live authority → Supabase
- GitHub model artifacts → Supabase reconciliation
- canonical joins and health gates → Supabase
- public dashboard/details/health → Supabase-backed app
- Google Sheet dashboard → frozen legacy / rollback reference only

The CSV files in `data/` remain worker artifacts and recovery inputs; they are no longer the user-facing production database.

## Reliability principles

- HKJC decides which matches are bettable.
- Finished and non-selling matches do not enter the Forebet target gate.
- `FBxxxx` is the canonical event key.
- Alias learning is persistent and confidence-gated.
- Partial source refreshes do not erase valid active models.
- Scrapes fail closed instead of silently replacing good data.
- Routine Forebet production uses zero ScraperAPI credits.
- Shadow models cannot influence Best Bet until validated out of sample.
- Production does not depend on ChatGPT, Opera, or a local computer after setup.

## Runtime workflow policy

The production pipeline is intentionally split into three planes to prevent connection storms and duplicate work.

### 1. Live plane — Supabase owns freshness

- HKJC live odds: every 2 minutes.
- Live score: every 2 minutes, staggered from HKJC live odds.
- Live layer / shadow comparison: every 2 minutes.
- Live source shadow: every 5 minutes.
- HKJC upcoming authority: every 15 minutes.
- Phase 4 quotes: every 2 minutes.
- GitHub `HKJC Live Odds Fallback` is manual/code-change fallback only and must not become a scheduled production heartbeat.

### 2. Static plane — batch, hash, then sync

- `Supabase Static Data Push` runs at minute 07 and 37 only, plus manual/config-change runs.
- Do not add `workflow_run` fan-out to this workflow.
- All current CSV artifacts are sent in one OIDC-authenticated batch request.
- Supabase compares SHA-256 hashes and uploads only changed files.
- Canonical sync runs only when canonical inputs changed.
- `sync-fast-tracker` reads Supabase Storage first; GitHub raw files are fallback only.
- Pure telemetry/identity diagnostics must stay out of the canonical hot path.

### 3. Slow enrichment plane

- Alias maintenance: hourly.
- Phase 3 GitHub identity evidence runner: hourly.
- Feed recovery watchdog: every 30 minutes.
- API-Football detail: every 30 minutes; base layer every 6 hours.
- Football-Data and archive/evaluation workloads remain daily or otherwise bounded.

### Guardrails

- Avoid new 1-minute external HTTP cron jobs unless live trading freshness genuinely requires them.
- Prefer staggered schedules over multiple jobs firing on the same minute.
- Prefer one batch request over one request per file.
- Prefer change detection over unconditional rebuilds.
- A health `WARN` for source absence/staleness is not a pipeline failure.
- Do not call disabled `sync-fast-tracker` modes such as `live` or `archive`.
- One subsystem should have one production owner; GitHub and Supabase must not both poll the same live source on the same cadence.
