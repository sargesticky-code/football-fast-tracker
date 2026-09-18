# Fast Tracker implementation phases

This is the mandatory build order. Do not skip a phase because a later feature
looks useful.

## Phase 0 — Production correctness

Goal: current Sheet and feeds must be truthful and stable.

- Fix live fixture identity / provider coverage gaps.
- Preserve HKJC as canonical event ID.
- Distinguish NO FOREBET, NO LOCAL MODEL, NO APWIN and SOURCE GAP.
- Keep Dashboard compact and readable.
- No scenario-based betting recommendations.
- No high-frequency HKJC live-market polling.

Exit gate:
- live-source gaps are diagnosable by source / identity reason
- Dashboard labels do not claim "NO MODEL" when another model exists
- source health is explicit

## Phase 1 — Post-match player database

Goal: build our own recent, match-level player evidence base.

Primary source: FotMob matchDetails.
Backup source later: Sofascore only if operationally reliable.

Store one row per player per completed HKJC-targeted match, including:
- HKJC event ID
- source match/team/player IDs
- kickoff / league / home-away
- starter / substitute / position / shirt number
- minutes and rating where supplied
- goals / assists / xG / xA where supplied
- shots / shots on target / chances / box actions where supplied
- passing / key passes where supplied
- tackles / interceptions / recoveries / duels / aerials where supplied
- goalkeeper saves / goals prevented where supplied
- cards and other supplied match stats
- raw normalized player-stat JSON so schema changes do not destroy information

Data policy:
- prioritize current/recent matches
- no 2012-era bootstrap
- initially backfill only a short recent window
- fail closed if match identity is uncertain
- cap requests and preserve last-good data

Exit gate:
- at least 50 completed HKJC matches with usable player rows
- player identity coverage >= 90% of players in captured lineups
- source/match quality stored for every row

## Phase 2 — Manager and tactical match database

Goal: derive actual styles from recent matches, not labels.

Use Phase 1 plus team match stats to learn:
- formation
- possession / territory
- shot creation
- corner generation / concession
- pressing / defensive actions where observable
- substitution timing
- behaviour when leading / drawing / trailing
- manager tenure boundaries

Exit gate:
- current manager identity and recent tactical sample for both teams
- no old-manager matches mixed into current-manager profile without a boundary

## Phase 3 — Pre-match feature/model layer

Goal: produce a current evidence model for every HKJC match where possible.

Priority:
1. confirmed/probable XI
2. recent individual-player data
3. availability/injuries
4. manager/tactical data
5. current team form
6. Forebet / DC / Pi / APWin / other model evidence
7. old team history only as weak fallback

This phase is where unsupported competitions such as Brazilian Serie B can
start receiving a local model without depending on Football-Data coverage.

Exit gate:
- model coverage reported by source
- no generic "NO MODEL" label
- unsupported-history competitions can use player/tactical evidence when enough exists

## Phase 4 — Time-segment scenario model

Only after Phases 1–3 are mature.

Segments:
- 0–15
- 16–30
- 31–HT
- 46–60
- 61–75
- 76–FT

Targets:
- scoring probability by side
- possession/control state
- shot / chance pressure
- corner pace and advantage
- expected score state

Exit gate:
- out-of-sample calibration on recent matches
- minimum sample thresholds by league / feature family
- no invented probability when sample is insufficient

## Phase 5 — Live scenario comparator

Compare the Phase 4 expected match path with actual live:
- possession
- shots / SOT
- xG when available
- box entries / big chances
- corners
- cards / substitutions
- momentum

The comparator is descriptive first. It does not recommend a bet until Phase 6.

## Phase 6 — Live market edge and betting signal

Only now compare calibrated match state against current HKJC HAD / HIL / CHL.

Output:
- current line / price
- model fair probability / fair line
- edge
- evidence
- model disagreements
- confidence
- BET / SMALL / WAIT / AVOID
- invalidation condition

Crowded-market / neglected-information signals belong here, not earlier.

## Current status

Phase 0: active
Phase 1: starting
Phase 2: not started
Phase 3: existing legacy models only; no new expansion until Phase 1
Phase 4: paused
Phase 5: paused
Phase 6: paused
