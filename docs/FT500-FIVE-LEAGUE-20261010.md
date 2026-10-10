# FT500 verified five-league expansion — 2026-10-10

## Why this is minimal
Same `trade.500.com` source XML + HTML, same `ft_500_spf_current` RLS
table, same GitHub OIDC publisher, same canonical fixture API and same
GitHub cron at minute 13/43. No additional quota, paid key, provider,
scraper, alias table, database cron, or rate increase.

## Grounded evidence
- One-shot GitHub runner [audit 38055080190](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38055080190):
  54 valid provider quotes at 2026-10-10 ~13:16 UTC.
  Source distribution: EPL 8, LaLiga 8, Serie A 8, Bundesliga 8, Ligue 1 4
  (36 of 54). Other leagues remain deliberately unmatched.
- [Live canonical dry-run 38055296194](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38055296194):
  13/13 parser/identity tests pass; 36/54 source rows uniquely join to canonical
  `match_id` with explicit home/away translation AND same league AND kickoff
  within ten minutes. Five simultaneous Bundesliga fixtures were paired
  uniquely by verified team pair, not kickoff-only.
- Publication was disabled during both audits.
- Supabase applied migration `20261010132309` extends service-only
  `ft_publish_500_spf` acceptlist to four additional named competitions
  and changes `ft_fast_flashscore_summary` join to match full canonical
  league. Verified `anon_execute=false`, `auth_execute=false`,
  `service_execute=true`, table RLS enabled and 8 existing rows preserved
  immediately after migration.
- Source `source_updated_at` is retained and reader accepts only
  <=24-hour source age and <=75-minute capture age for prematch reference.
  This is *not* independently verified bookmaker odds or a value model.
- Frontend already deployed and rendered for desktop/tablet/mobile in
  run 38053965869. Frontend source-label and value guards were tightened
  separately on release/ft500-spf-label-20261010.

## Release gate
Merge verified publisher changes after a passing 13-test live dry-run.
The workflow will execute once on first main push; verify it publishes actual
additional source-verified matches to same RLS table, then verify public
summary source context `CHINA_500_SPF`, value/EV suppressed, same match IDs.
A scheduled run success should never be inferred just because the workflow
is declared in YAML; inspect a `schedule`-triggered run separately.

## Recovery
Do not delete or rebuild the database. Previous league=EPL rows continue
working. On a regression, restore the prior code of
`scripts/capture_500_spf.py`; the DB accepts historical EPL-only payloads.
No new service, cron, or key to undo.

## Known outstanding issues
Forebet has no fresh accepted rows after 2026-09-28; GitHub-source
access/permission remains unresolved. No historical Forebet probability
is substituted for a new match. Public display/reuse permission for
external third-party data requires separate verification before any
commercial syndication.
