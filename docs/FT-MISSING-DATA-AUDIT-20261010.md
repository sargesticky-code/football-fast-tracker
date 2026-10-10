# FT-20261010 — Dashboard missing-data audit and minimal capture recovery

## User goal
Forebet-style 1X2, predicted score and average goals, live Flashscore
match details/lineups, international bookmaker prices where trustworthy,
lean Supabase/Railway/GitHub footprint. No HKJC producer. Do not
fabricate unknown quantities or treat national lottery SPF as live bookmaker quotes.

## Production baseline (read-only SQL, 2026-10-10 about 15:20 UTC)
The `ft_fast_flashscore_summary(48)` returns **256** canonical fixtures,
of which **144 upcoming within 48h** (the rest represent recent history).
It contains 20 non-null Forebet 1X2 predictions + 20 predicted scores,
36 stored detail payloads and 124 legacy odds-bearing fixture rows. Its
China-500 reference rows were zero at query time due to freshness gating;
this does not mean the 500 source store is empty.

**Source-truth coverage** in the same verification window:
- `forebet_predictions`: 545 historical records; **20 current 1X2 H/D/A
  + predicted score + avg goals** records from GitHub OIDC successful
  capture `38061748513`. No independently verified Forebet O/U,
  corners, power or own bookmaker prices in that fresh cohort (all 0/20).
  `forebet_supplement` source last updated 2026-09-19; not fresh.
- `bookmaker_odds_current`: 124 rows from a source capture at 2026-10-10
  13:43 UTC, 57 map to future-48h Canonical fixtures. These are stored
  bookmaker quotes, **not proof of presently actionable price freshness**.
- `market_odds_current`: 1124 records, latest odds_updated_at **2026-10-05**.
  Treat as historical; never fill current odds from it.
- `ft_500_spf_current`: 36 stored 500.com reference matches; no record
  met the strict combined price-source/update and 75-minute capture
  freshness requirement in the audited fixture subset. Do not convert
  reference SPF into EV/Value.
- `lineup_evidence_current` has historical player rows; however the
  official `phase2_lineup_coverage_display_current` reported **150
  upcoming MISSING** lineup states in its fixture universe. Historic
  confirmed XI must never be projected as confirmed for future matches.
- Supabase pg_cron jobs are not a simple duplicate list: 24+ active
  schedules independently support live, source ingest, shadow, lineup,
  health and pricing. Identical SQL command hash check previously
  found zero duplicate active jobs. Do not disable a different live
  authority job solely because its name sounds similar.

## Demonstrated alias reuse
The project already has **952 VERIFIED Forebet team aliases** in
`team_alias_registry_v2`. Following the historical verification
confidence minimum of 0.95 plus the existing source-family subset,
we snapshotted 710 source aliases / 1013 unique allowed target names into
`data/forebet_verified_aliases.json` (~54KB), no runtime DB query.

The browser's **single existing Forebet 1X2 day page** now selects names
via the verified local crosswalk. Final identity still demands a unique
canonical match ID, separately verified source league, same home+away
team identity, one-minute corroborated kickoff UTC, whole-batch clock
cohort, 1X2 probability checks and real predicted score/avg goals. Real
Forebet source names are never rewritten as canonical names in stored
publisher evidence. A verified alias match is tagged and conservatively
scored 0.985, while an exact match is tagged and scored 0.995; both
remain above the existing OIDC publisher's 0.94 model gate.

[GitHub read-only acceptance 38063095394](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38063095394):
**14/14 unit tests pass**; source official page 1115 DOM rows,
**21** strictly matched fully modeled fixtures across 13 leagues:
**20 exact + 1 alias**. 4 candidates failed league/time/identity and 2
failed required source fields or source clock. All remain unknown, no
database writes during proof. One-shot workflow was removed from final
branch to avoid additional scheduled or push-triggered captures.

This is incremental (+1), not a complete cure for missing-data coverage.
The daily source workflow stays exactly once at 00:15 UTC plus manual
dispatch, with NO push trigger; therefore production remains at 20
until the next successful natural/manual run. Never describe a test
capture as a production publication.

## Proven distinct root causes and priorities
1. **Coverage gap:** 144 future-48h fixtures versus 20 fresh Forebet
   models. Some are not on the one official date's 1X2 source, some lack
   verified competition/team/time mapping, and some do not publish all
   required values. The alias snapshot improves one proven case without
   adding a request or introducing fuzzy IDs.
2. **Source-market absence:** Over/Under, corners and team power fields
   are not in the current verified 1X2 parser/source surface, so cannot
   be filled merely by another DB join. Need distinct source evidence
   before adding a second page/request.
3. **Quote freshness:** historical market-odds rows and aged SPF quote
   timestamps must remain unavailable. Existing Bet365 quotes are
   recorded separately, with independent age/authority checks.
4. **Upcoming lineups:** future confirmed lineups cannot be derived
   from historic player evidence. Keep predicted/confirmed separate.
5. **Transport/render:** earlier 24h homepage range and hidden
   responsive search were actual frontend defects, already fixed on
   Railway commit `da6472f81009a58e206ca2e9f96dc95dc63ec82a` and
   browser-accepted run `38061987273` for desktop/tablet/mobile.

## Safety/continuity
No new cron job, paid provider, Supabase table/migration, Edge function,
Railway service, scraper API/endpoint, or increased fetch frequency.
The official Forebet source visit stays once daily. Legacy HKJC:
prefixes identify historic internal teams; no HKJC odds API/source is
called by this implementation. Keep existing Flashscore, live,
injury/lineup, 500 SPF and all protected publisher gates untouched.

## Recovery / check after next natural scheduled run
Review GitHub Forebet Canonical Daily workflow, require a real
`schedule` event and `FOREBET_CANONICAL_STRICT_PROOF` with
`verified_alias_matches` and `FOREBET_PUBLISHED`; reconcile
`forebet_predictions.fetched_at` and
`ft_fast_flashscore_summary(48)` plus one rendered fixture. If alias
coverage regresses, revert only alias-module + local JSON + capture
changes, leaving the existing exact-name fallback and all other
pipeline phases intact.
