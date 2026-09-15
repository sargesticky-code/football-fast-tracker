# Football Fast Tracker

Automated football data feeds for the Fast Tracker Google Sheet. Production data is keyed by the HKJC `FBxxxx` event id so source joins do not depend on loose team-name matching inside the Sheet.

## Production architecture

### 1. HKJC — fixture authority and primary market

The daily production job talks directly to the public HKJC football GraphQL endpoint through a pinned copy of `sososo829/hkjc-football-scraper`.

It captures:

- the full current HKJC fixture list;
- official `FBxxxx` front-end ids;
- kickoff and match status;
- pools currently offered;
- current HAD home/draw/away prices.

Normalized outputs:

- `data/hkjc_current.csv` — all current/retained HKJC fixtures, including status and HAD availability;
- `data/hkjc_targets.csv` — only pre-event fixtures inside the modelling horizon with a complete, selling HAD triplet.

The previous Google-Sheet HKJC Source Snapshot is retained only as a fallback if the direct target file is missing, invalid, or stale. It is no longer the primary production gate.

### 2. Forebet — external prediction model

Only dates and matches that are currently bettable at HKJC are considered. The workflow fetches Forebet through ScraperAPI, joins it to the HKJC target set, and writes only matches with a complete 1X2 model probability triplet.

Output:

- `data/forebet_current.csv`

The production CSV is not overwritten by a zero/invalid scrape.

ScraperAPI is deliberately cost-capped. Each successful date request currently costs 10 credits. The normal horizon may require up to two date requests, so the expected ceiling is about 20 credits for one daily production run unless the source pricing changes. Avoid unnecessary manual reruns.

### 3. Opta Power — independent global club strength

The Forebet feed is enriched with current Opta global club power ratings and confidence-matched team names. A coverage health gate prevents a suspiciously weak enrichment from being accepted silently.

Opta is a strength signal, not a replacement for Forebet match probabilities.

### 4. Bet365 — secondary market benchmark

Bet365 is intentionally secondary because it requires a real Chromium/Playwright session and is therefore more fragile than HKJC GraphQL.

The Bet365 job first reads current HKJC targets. It installs/runs Playwright only when a currently bettable HKJC fixture belongs to a competition supported by the pinned scraper. The resulting prices are then matched back to the canonical HKJC `FBxxxx` id and rejected if team matching is low-confidence.

Output:

- `data/bet365_current.csv`

An empty file means there is currently no supported Bet365/HKJC overlap; it is not a production failure.

### 5. Dixon-Coles + Pi — independent shadow model

`penaltyblog==1.12.2` is pinned for the statistical model layer. The daily shadow model trains only from free historical results on football-data.co.uk. It deliberately does **not** use Forebet probabilities, HKJC prices, Bet365 prices, or Opta ratings as training inputs.

For supported leagues it produces:

- Dixon-Coles H/D/A probabilities;
- expected home/away goals;
- Over 2.5 probability;
- Pi H/D/A probabilities;
- Pi home/away ratings and rating difference.

Coverage is fail-closed. Fixtures without adequate free historical coverage remain in the file with `quality=UNSUPPORTED_HISTORY` and blank model probabilities rather than receiving invented values.

Output:

- `data/model_current.csv`

This is a **shadow** model: it is visible in Fast Tracker but does not yet change Best Bet selection. Promotion should depend on walk-forward RPS, log loss, calibration, ROI and closing-line-value evidence.

### 6. CatBoost / stacked ensemble — research only

The heavier `jdgoated1/football-predictor` stack is pinned in a manual-only workflow. It combines Dixon-Coles, Elo/Pi, tree models and calibration, but it is deliberately not retrained every day while the Fast Tracker shadow sample is still small.

`.github/workflows/catboost_research.yml` must be manually dispatched and preserves only the research log as a short-lived artifact. It cannot affect production feeds.

## Schedule (Hong Kong time)

- **06:45** — direct HKJC GraphQL → HKJC target gate → Forebet → Opta
- **07:05** — Dixon-Coles + Pi shadow model
- **07:15** — Bet365 benchmark, only when a supported HKJC competition is present
- CatBoost ensemble — manual research only

## Google Sheet staging

The Fast Tracker workbook reads the public CSVs with `IMPORTDATA`:

- `ForebetFeed` → `data/forebet_current.csv`
- `HKJCFeed` → `data/hkjc_current.csv`
- `MarketFeed` → `data/bet365_current.csv`
- `ModelFeed` → `data/model_current.csv`

`Fast Tracker Live` joins Bet365 and shadow-model fields by HKJC `FBxxxx`, keeping source ingestion separate from dashboard formulas.

## Reliability principles

- HKJC decides which matches are bettable.
- Finished/non-selling matches do not enter the Forebet target gate.
- `FBxxxx` is the canonical event key wherever available.
- Scrapes fail closed instead of silently replacing a good feed with empty/bad data.
- Expensive sources run only when needed.
- Shadow models cannot influence Best Bet until validated on genuinely out-of-sample data.
- No production workflow depends on ChatGPT, Opera, or a local computer after setup.
