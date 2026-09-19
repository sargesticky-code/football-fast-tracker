# Multibetter V1

Multibetter is an experimental multi-source football prediction framework developed separately from Fast Tracker.

## Matching architecture

Multibetter uses **Forebet as the team-name matching hub**.

The existing Fast Tracker Forebet -> HKJC alias bridge is already mature, so new prediction sources do not maintain their own HKJC alias tables.

```text
APWin ---------\
Statarea -------\
BetClan ---------> Forebet team key -> existing Forebet/HKJC alias -> HKJC event ID
Other models ---/
```

HKJC remains the final fixture/odds/display authority, but new source matching is performed against the Forebet reference names.

## Rules

- Fast Tracker remains production and is not modified by Multibetter work.
- HKJC event ID remains the final event key.
- Forebet team names are the canonical **matching hub** for external prediction sources.
- Existing Forebet -> HKJC aliases are reused; do not create a separate HKJC alias table per source.
- Each new source only needs Source -> Forebet aliases where exact names differ.
- Source data flows through: raw -> normalized -> Forebet-matched -> HKJC-linked -> consensus.
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

The first target source is APWin. APWin candidates must first resolve to the correct Forebet fixture/team key. Only after that does the existing Forebet -> HKJC bridge supply the HKJC event ID and display names.

## Planned data flow

```text
HKJC fixtures
      ^
      | existing Forebet/HKJC alias bridge
      |
Forebet reference fixtures / team keys
      ^
      |
      +---- APWin
      +---- Statarea
      +---- BetClan
      +---- FootballSuperTips
      +---- future models
      |
      v
strict Source -> Forebet matcher
      |
      v
HKJC-linked normalized records
      |
      v
market-specific consensus
      |
      v
HKJC price comparison / edge layer
```
