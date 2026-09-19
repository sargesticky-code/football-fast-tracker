# Multibetter V1

Multibetter is an experimental multi-source football prediction framework developed separately from Fast Tracker.

## Rules

- Fast Tracker remains production and is not modified by Multibetter work.
- HKJC fixtures are the canonical fixture layer.
- HKJC event ID is the preferred primary key.
- Source data flows through: raw -> normalized -> matched -> consensus.
- NO DATA is safer than a wrong match.
- Senior / Women / U21-U23 / reserve / B-team mismatches are rejected.
- Source failures are isolated and must not blank other sources.
- Every source result carries fetched_at, match confidence and health status.
- Source weights are market-specific; one global source weight is not allowed.

## Initial layout

```text
multibetter/
  src/multibetter/
    models.py
    normalization/teams.py
    matching/matcher.py
    consensus/engine.py
    health/status.py
    sources/base.py
    sources/apwin.py
  tests/
```

## V1 objective

Build a trustworthy source registry and matching layer before connecting any dashboard.

The first target source is APWin because the current Fast Tracker APWin pipeline has false-positive fixture matching. Multibetter must prefer NO_MATCH over a plausible but wrong fixture.

## Planned data flow

```text
HKJC canonical fixtures
        |
        +--> source adapters (Forebet / APWin / Statarea / BetClan / ...)
        |
        v
normalized source records
        |
        v
strict fixture matcher
        |
        v
market-specific consensus
        |
        v
HKJC price comparison / edge layer
```
