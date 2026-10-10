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
