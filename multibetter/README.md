# Multibetter V1

Multibetter is developed separately from Fast Tracker. Fast Tracker main remains production and is not modified by Multibetter work.

## Approved V1 architecture: one bridge only

The external GitHub multi-source framework is responsible for collecting and aligning its own prediction sources.

Multibetter does **not** maintain separate APWin -> HKJC, BetClan -> HKJC, Statarea -> HKJC, etc. mappings.

```text
External GitHub multi-source framework
  Accumulator / BetClan / FootballSuperTips / Forebet / Prematips / Statarea / future sources
                         |
                         v
              GitHub multi fixture
                         |
                  GitHub Forebet row
                         |
                         v
        ONE bridge: GitHub Forebet -> OUR Forebet
                         |
                         v
        existing OUR Forebet <-> HKJC alias
                         |
                         v
                    HKJC event ID
```

HKJC remains the final fixture, price and display authority. OUR Forebet remains the existing bridge to HKJC.

### Why this is faster

Both sides use Forebet as the reference source, so most GitHub-Forebet -> OUR-Forebet matches should be exact. Only genuine Forebet naming/version differences need the small bridge alias table.

We do not repeat team-alias work for every prediction provider.

## Production matching rules

- The only Multibetter-owned identity bridge is GitHub Forebet -> OUR Forebet.
- HKJC event ID remains the final event key.
- Existing OUR Forebet -> HKJC aliases are reused unchanged.
- Date and kickoff must be compatible.
- Home and away orientation must match.
- Senior / Women / U21-U23 / reserve / B-team mismatches are rejected.
- NO MATCH is safer than a false match.
- No fuzzy source-to-HKJC production fallback.
- Source failures are isolated and must not blank the whole multi-source fixture.

## Data flow

```text
github_multi_raw
      |
      v
github_multi_fixture
      |
      | contains github_forebet_home / github_forebet_away
      v
bridge_github_forebet_to_our_forebet()
      |
      v
HKJC event_id + HKJC names + HKJC odds
      |
      v
multi-source consensus
```

## APWin note

The inspected public GitHub project currently contains adapters for Accumulator Generator, Forebet, BetClan, FootballSuperTips, Prematips and Statarea. It does not currently contain an APWin adapter.

The APWin collector prototype in this branch is therefore parked as an optional future source adapter. It is not part of the approved V1 identity-matching path unless APWin is first incorporated into the external multi-source fixture layer.

## V1 objective

1. Import the GitHub framework's multi-source fixture output.
2. Read its selected Forebet fixture identity.
3. Bridge that single Forebet identity to OUR Forebet.
4. Reuse the existing OUR Forebet -> HKJC event mapping.
5. Build consensus only after the fixture has a trusted HKJC event ID.


## Long-term alias maintenance

Multibetter uses an exact-first, verified-exception model.

- Exact GitHub-Forebet -> OUR-Forebet names require no alias row.
- Verified exceptions live in `multibetter/data/forebet_bridge_aliases.csv`.
- New possible mappings are accumulated in `multibetter/data/forebet_bridge_candidates.csv`.
- Candidates never silently become production aliases.
- Repeated evidence can mark a candidate `REVIEW_READY`, but final production use remains a verified/static mapping.
- Conflicting targets and team-class changes block the mapping.
- `multibetter/scripts/alias_health_report.py` audits both the existing Fast Tracker alias files and the Multibetter bridge tables.

This keeps the alias table improving over time without turning fuzzy matching into hidden permanent state.


## Current build pipeline

The V1 current builder is now available:

```bash
python -m multibetter.scripts.build_current \
  --source-dir multibetter/incoming/current
```

Expected source directory:

```text
forebet.csv              required anchor
accumulator.csv          optional
betclan.csv              optional
footballsupertips.csv    optional
prematips.csv            optional
statarea.csv             optional
```

The builder:

1. loads the fast GitHub-Forebet -> OUR-Forebet alias cache;
2. groups optional upstream sources around each GitHub Forebet row;
3. resolves the fixture using cache first;
4. on cache miss, uses exact date/time/league and home/away orientation;
5. writes deterministic newly learned aliases back to the cache immediately;
6. reuses those aliases later in the same run;
7. emits `multibetter_current.csv` and health counters;
8. updates last_seen / observation_count when cached aliases are reused.

A manual branch-only workflow exists at `.github/workflows/multibetter_v1_build.yml`.

It deliberately has **no cron schedule yet**. Scheduling should only be enabled after a live current multi-source collector is connected, so the system never overwrites a good output with an empty input run.
