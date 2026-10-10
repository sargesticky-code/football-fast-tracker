# FT-FOREBET-LEAN — 2026-10-10 release checkpoint

## Scope and architecture
The owner's existing Forebet predictions were stale since 2026-09-28. Plain
GitHub HTTP and ordinary Chromium returned 403. An external upstream Repo
(Alm77ar/Forebet-Scraper) provided a working architecture, adapted into
original minimal scripts. No upstream source code was copied; license for the
upstream repository is not declared. Current implementation uses a one-job
ephemeral local browser helper inside GitHub Actions.

New single daily producer: `.github/workflows/supabase_private_ingest.yml`,
retaining its existing trusted OIDC workflow path and existing
`forebet-canonical-publish` Edge service. The legacy `workflow_run`
trigger and HKJC CSV replay are gone. The runner fetches **one official
date's** 1X2 page, loads `#mrows` once, then extracts at most 80 relevant
DOM rows from existing Canonical fixtures instead of downloading huge HTML.

Scripts:
- `scripts/forebet_browser_source.py`: bounded browser and 1,200k-character
  in-browser extract from a canonical team-pair allowlist; no extra canonical
  API call, no cookies, user accounts or screenshots persisted.
- `scripts/capture_forebet_canonical_light.py`: verifies complete H/D/A
  summing 98–102%, predicted score, avg goals, explicit league code, exact
  unique home/away team IDs, minute-level kickoff; independent source display
  clock corroborated against Canonical UTC in a cohort of at least 8 matches,
  3 leagues, zero duplicate IDs.
- `scripts/forebet_canonical_source_probe.py`: canonical identity/model
  validators, reused; not a second capture job.
- `tests/test_capture_forebet_canonical_light.py`: nine deterministic
  failure-path tests.

## Real evidence before release
- Earlier upstream one-shot run 38058207762: 25 exact team name candidates;
  23 parseable source display clocks aligned with canonical UTC to the
  minute, 2 unparseable. The Forebet `time datetime` attribute is **date
  only**; never claim it includes UTC.
- New strict actual source run
  [38059043500](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38059043500):
  1,115 expanded source fixtures, 25 name candidates, **13 strict
  fully modeled matches** across 6 leagues, 10 rejected on strict
  league+clock+identity, 2 rejected on missing/invalid clock.
  6 previous tests + 9 new tests pass.
- Rebuilt/shortened collector run
  [38059509038](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38059509038):
  identical 13 strict live source models; 9/9 tests green.
- DB read-only cross-check confirms tested FS/FB match IDs are already
  present in `public.matches`, `public.forebet_availability` and
  `public.active_canonical_fixture_current`; no new schema/table needed.
- Before publication `forebet_predictions` had 525 historical records,
  newest 2026-09-28. No old models are rewritten as new.

## Production gates
- Publisher remains exactly the existing service-role, OIDC-scoped
  `ft_publish_forebet_canonical`, not a new endpoint.
- Main on-push bootstrap once, then single scheduled job daily at
  00:15 UTC (08:15 HKT) covering next date; optional manual dispatch.
- After publish, require real DB count, source-time and unique identity audit,
  then public Phase1 feed `forebet` H/D/A, `forebetDetail.predictedScore`
  and `forebetDetail.ou25.avgGoals`. Never substitute source SPF implied
  odds for Forebet.
- No new Supabase cron, extra API, parallel broad scraping, rate increase,
  scraper proxies, third-party forecast labeling or public license claim.
- The source may be temporarily blocked by Forebet; failed capture means
  no publication, not replaying old data as fresh.

## Clean recovery
Disable scheduled Forebet workflow via the existing GitHub workflow state,
or restore prior `supabase_private_ingest.yml` (manual/OIDC only) without
touching existing tables, Flashscore, 500.com and public app.
Prior Forebet rows remain historically stored; the 72h read-time gate
suppresses stale forecasts.

## First production acceptance — 2026-10-10
- [PR45 merged](https://github.com/sargesticky-code/football-fast-tracker/pull/45), squash `be84ea318c1634d4498ac76c459129be015722dd`.
- First authenticated OIDC GH Action [38059751481](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38059751481) SUCCESS: one bounded official date page (1,115 expanded DOM rows), 13 strict verified models, **13/13 written to existing Supabase `forebet_predictions`**, and **13 actual public Phase1 models** with H/D/A probabilities, predicted score and average goals. No false value/odds claim.
- Independently checked source row provenance: e.g. Liverpool–Man City (FB6338) Forebet H/D/A **16/34/50**, predicted score **1 - 2**, average goals **2.71**; source model snapshot captured 2026-10-10T14:29:25Z. The forecast is a forecast, not observed match result.
- [PR46 merged](https://github.com/sargesticky-code/football-fast-tracker/pull/46), squash `2b27c81fa0e3c2f72b7090c0f6fac17a3d79061b`: retired redundant Forebet supplement capture workflow (removed push trigger, revoked write permission, job non-executable). Legacy Forebet Daily was already non-executable. Old `workflow_run` chaining in `supabase_private_ingest.yml` replaced with single canonical daily capture.
- Active Supabase cron normalized-command audit showed **zero exactly duplicated active job SQL commands**; independently scoped Flashscore, lineup, live, and price jobs remain untouched.
- No new table, migration, new service, extra Supabase cron or paid API. GitHub Forebet official capture scheduled **once daily 00:15 UTC**; bootstrap was a `push` run, so **natural scheduled execution is not yet proven**.
- Limitations: other Forebet markets (O/U, corners, power, bookmaker price) are **still unknown**, not filled with guessed values. Only 1X2 + predicted score + average goals are source verified. The 12 non-approved name candidates remain rejected.
- Related public UI fix: original site defaulted to a 24h summary and capped initial display at 30 rows, hiding tomorrow's later fixtures. Isolated app release `release/ft-forebet-horizon-20261010` changes only indexed summary horizon to 48h and adds user-triggered client-only +30 pagination; [QA 38060552423](https://github.com/sargesticky-code/fast-tracker-app/actions/runs/38060552423) green and Railway deployment `afa46960-c962-4eed-901d-efebd441aa49` SUCCESS. Responsive browser verification is a separate release gate.

## Final 2026-10-10 continuation — 20 models, responsive proof, no code-push recapture
- [PR47 merged](https://github.com/sargesticky-code/football-fast-tracker/pull/47), squash `bb91ba64c8e74697e54efc641bfac633328ff1cd`: seven source league IDs, **each copied from observed same-minute Forebet home/away + Canonical kickoff records** in older run 38058207762. No fuzzy automatic league learning, new source URL, or extra page capture. Ten deterministic unit tests GREEN in [38061706198](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38061706198). Temporary QA workflow removed after passing.
- New verified production [38061748513](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38061748513) SUCCESS: 1,115 DOM rows in the same single Forebet source page, 25 canonical-name candidates, **20 fully verified models / 13 league competitions**, 3 league/time/identity exclusions plus 2 unparseable/invalid source rows. **20/20 OIDC publisher writes** to existing `forebet_predictions`; public Phase1 summary **20 of 257 canonical matches** contain complete Forebet model data. Database now 545 total historical+current records, newest `2026-10-10T14:59:25.735955Z`.
- Measured present fields for these 20: **20/20 H/D/A, correct-score forecast, average goals**. Separate Forebet Over/Under, corners, team-power and own odds price are **0/20**. Leave unknown rather than manufacture missing source-specific content. 500 SPF references are never labelled Forebet probabilities.
- [PR48 merged](https://github.com/sargesticky-code/football-fast-tracker/pull/48), squash `29c497d40f99c848218d714f391aac5d041e9031`: removed `push` trigger from the sole Forebet production workflow after bootstrap and successful refresh. **ONLY one scheduled capture per day at 00:15 UTC plus explicit manual workflow_dispatch**; code edits cannot cause duplicate network runs. Neither legacy Forebet Daily nor Forebet supplement refresh is executable. Independent source pipelines remain unmodified.
- Public frontend Railway `fast-tracker-public` deployed commit `da6472f81009a58e206ca2e9f96dc95dc63ec82a`, deployment `150e57ef-f640-4ed9-972a-99397de2dc88` SUCCESS. Indexed canonical homepage summary now covers 48h rather than 24h; initial rendering stays 30 matches, further matching rows expand by +30 **locally in browser** without another Forebet capture. Tablet/mobile search made visible with narrowly scoped CSS rules.
- Complete real public browser test [38060240610](https://github.com/sargesticky-code/fast-tracker-app/actions/runs/38060240610) latest attempt SUCCESS on 1440x900, 820x1180, 390x844: EPL Liverpool–Man City model H/D/A 16/34/50, predicted 1–2, average 2.71. Expanded separate QA [38061987273](https://github.com/sargesticky-code/fast-tracker-app/actions/runs/38061987273) SUCCESS **six fixture-size pairs**: additionally Greek Super League Kifisia–Panetolikos H/D/A 23/40/37, predicted 0–0, average 1.88 all visible on desktop/tablet/mobile.
- Remaining natural scheduling caveat: CI bootstrap and code-push capture runs proved browser+OIDC+DB+API+UI, but the **next natural 00:15 UTC schedule has not yet run**. Do not claim 24h recurring reliability until a natural run is observed. Source access may later deny one capture; fail closed and retain original event freshness timestamp.
