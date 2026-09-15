# Football Fast Tracker

Automated data feeds for the Fast Tracker Google Sheet.

## Forebet feed

The repository runs a scheduled GitHub Action that fetches current/upcoming Forebet football predictions and writes a normalized CSV to `data/forebet_current.csv`.

The Google Sheet reads the CSV with `IMPORTDATA`, so the production feed does not depend on ChatGPT, Opera, or a local computer after setup.

Schedule target: once daily around 06:45 Hong Kong time, with manual and push-trigger support for recovery/testing.

## One-time proxy setup

Forebet currently returns HTTP 403 to GitHub-hosted runner IPs. The scraper therefore supports ScraperAPI as the production fetch layer.

Create the repository Actions secret `SCRAPERAPI_KEY` under **Settings → Secrets and variables → Actions → New repository secret**. Put the ScraperAPI API key in the secret value. Never commit the key into this repository or the Google Sheet.

The workflow reads the secret automatically. It first requests Forebet through ScraperAPI and only falls back to direct HTTP for diagnostics. The CSV is not overwritten when a scrape returns zero fixtures.
