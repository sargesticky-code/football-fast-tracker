# Football Fast Tracker

Automated data feeds for the Fast Tracker Google Sheet.

## Forebet feed

The repository runs a scheduled GitHub Action that fetches current/upcoming Forebet football predictions and writes a normalized CSV to `data/forebet_current.csv`.

The Google Sheet reads the CSV with `IMPORTDATA`, so the production feed does not depend on ChatGPT, Opera, or a local computer after setup.

Schedule target: once daily around 06:45 Hong Kong time, with manual and push-trigger support for recovery/testing.
