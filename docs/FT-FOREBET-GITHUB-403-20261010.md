# FT-Forebet access and capture recovery — 2026-10-10

## What actually broke
1. Legacy `.github/workflows/forebet_daily.yml` was deliberately retired. It depended on outdated HKJC fixture targeting, wrote CSV and used an optional paid `SCRAPERAPI_KEY` transport; that workflow is not a valid canonical-Supabase feed.
2. The replacement `scripts/forebet_canonical_source_probe.py` was still read-only and triggered offline tests only by default. The previous six offline checks did NOT prove a current real scrape; there are 525 historical database rows, most recently fetched 2026-09-28.
3. Actual GitHub-hosted access fails *before HTML parsing*. [URL diagnostic 38056183183](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38056183183): all four official Forebet URLs (dated 1X2, homepage, today, top Europe) returned HTTP 403.
4. [Plain Chromium diagnostic 38056402032](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38056402032): homepage and today 1X2 both returned 403, title `Just a moment...`, no match or probability DOM nodes. The follow-up run [38056580556](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38056580556) also retained 403 after a normal browser initialization wait. No proxy, bypass, CAPTCHA solver or paid API was used.
5. Separate code defect: original `parse_forebet_rows()` did not output `source_kickoff_iso`, even though the canonical guard strictly required it; thus real access alone could still have produced zero verified rows. That bug is now fixed on this PR branch: take only explicit offset-bearing HTML `time[datetime]`, convert to UTC; timezone-naive date/time is rejected, not guessed. [Unit run 38056531197](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38056531197) passes six source/parser identity tests, including naive-time rejection.

## Immediate impact and gate
GitHub-hosted free-only Forebet scrape is not a verified working production source. Do not enable a daily schedule that repeatedly hits 403, do not use the old HKJC workflow, and do not publish historical forecasts as current.

The official site still displays current H/D/A, correct-score prediction and avg-goals in a regular user-facing browser/search index; its existence does not establish server-to-server access permission or a usable GitHub API.

Personal, noncommercial display scope is relevant but does not make inaccessible automation reliable, or change the site's posted access/reproduction terms. Do not present third-party prediction models as Forebet.

## Clean restoration criteria
- Obtain an authorized/reliable official data transport (for example permission/allowlisting or permitted consumer export), or another actual tested source; no assumption a GitHub scraper library fixes network 403.
- On GitHub runner, capture at least three future official fixtures with explicit provider UTC timestamps and full H/D/A (summing ~100%), pick, score, and average goals.
- Reconcile each with a unique *existing* canonical ID using both team identities, league and verified kickoff; no fuzzy or kickoff-only mapping.
- Publish only verified prospective model data through existing OIDC publisher and read-path freshness gates. Prove DB -> API -> rendered UI before adding a low-frequency schedule.
- Preserve the independent current Flashscore stats and China 500 SPF reference odds pipelines. No new DB/schema/cron/paid key is needed until the capture gate passes.
