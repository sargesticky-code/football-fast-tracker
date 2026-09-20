# Long-term alias maintenance policy

## Purpose

Keep Multibetter and Fast Tracker team identity stable as more leagues and sources are added.

The system must improve coverage over time without silently teaching itself bad aliases.

## Authority chain

```text
GitHub multi-source fixture
  -> GitHub Forebet name
  -> Multibetter Forebet bridge
  -> OUR Forebet name
  -> existing Fast Tracker Forebet/HKJC registry
  -> HKJC event ID / display name
```

The existing Fast Tracker alias files remain authoritative for OUR Forebet -> HKJC:

- data/team_alias_manual.csv
- data/team_alias_registry.csv
- data/team_alias_unresolved.csv

Multibetter maintains only the small GitHub-Forebet -> OUR-Forebet exception layer.

## Resolution order

1. EXACT
   - Same Forebet name on both sides.
   - Accepted automatically.
   - Not written as an alias because identity needs no alias.

2. VERIFIED_ALIAS
   - Explicit entry in multibetter/data/forebet_bridge_aliases.csv.
   - Accepted in production.

3. CANDIDATE
   - A likely same-team naming difference discovered from fixture context.
   - Never accepted into production merely because it is fuzzy.
   - Evidence is accumulated across observations.

4. CONFLICT
   - One external name points to multiple OUR Forebet names, or team class conflicts.
   - Production use is blocked.

5. UNRESOLVED
   - No safe mapping.
   - Keep NO DATA / NO MATCH rather than force a mapping.

## Candidate evidence

Each candidate tracks:

- github_forebet_name
- proposed OUR Forebet name
- first_seen
- last_seen
- observation_count
- best / latest similarity
- distinct fixture opponents
- event IDs observed
- team class
- status / reason

A candidate becomes REVIEW_READY when:

- observation_count >= 3
- at least 2 distinct opponent contexts
- no conflicting target
- same team class
- similarity >= 0.85, or stronger fixture-level evidence exists

REVIEW_READY is still not production-approved automatically. A verified/static alias remains the production rule.

## Conflict rules

The audit must flag:

- same source alias -> multiple canonical targets
- same alias appearing in both verified and rejected sets
- senior -> U21/U23/B/reserve/women class changes
- target no longer present in any known OUR Forebet history
- duplicate verified alias rows with different metadata
- circular aliases

## Long-term health metrics

Track every run:

- exact bridge rate
- verified alias rate
- unresolved rate
- conflict count
- new candidate count
- review-ready count
- aliases not seen recently
- aliases used successfully in the last 30/90 days

The target is not 100% alias coverage. The target is:
- high exact-match rate
- small verified exception table
- zero silent conflicts
- zero forced matches

## Current baseline

Audit of current Fast Tracker alias files on 2026-09-20:

- team_alias_registry.csv: 544 rows
- team_alias_manual.csv: 33 rows
- registry conflicts: 0
- manual conflicts: 0
- unresolved rows: 0

This is a healthy starting point.
