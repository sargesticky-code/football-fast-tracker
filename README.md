# Football Fast Tracker

Automated football data feeds for the Fast Tracker Google Sheet. Production data is keyed by the HKJC `FBxxxx` event id, so source joins do not depend on loose team-name matching inside the Sheet.

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

## Google Sheet staging

The Fast Tracker workbook reads the public CSVs with `IMPORTDATA`:

- `ForebetFeed` → `data/forebet_current.csv`
- `HKJCFeed` → `data/hkjc_current.csv`
- `MarketFeed` → `data/bet365_current.csv`
- `ModelFeed` → `data/model_current.csv`

`Fast Tracker Live` joins all model and market fields by HKJC `FBxxxx`. The Dashboard remains a concise view; full current coverage stays in `Fast Tracker Live`.

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
