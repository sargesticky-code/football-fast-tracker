# Long-term alias maintenance policy

## Core principle: cache first, deterministic fallback only on cache miss

The approved production order is:

```text
1. Exact/alias cache lookup
        ↓ miss
2. Exact DATE + exact normalized TIME + LEAGUE bucket
        ↓
3. Match HOME(team1/left) and AWAY(team2/right) orientation
        ↓
4. Resolve team names only inside that small bucket
        ↓ unique
5. Match fixture
        ↓
6. Write newly learned team aliases back to alias cache
        ↓
7. Next occurrence uses fast alias lookup
```

This is intentionally asymmetric: expensive matching is a **one-time learning cost**. Repeated fixtures for the same team names should use O(1) dictionary lookups.

## Authority chain

```text
GitHub multi-source fixture
  -> GitHub Forebet name
  -> Multibetter alias cache
  -> OUR Forebet name
  -> existing Fast Tracker Forebet/HKJC registry
  -> HKJC event ID
```

Fast Tracker's existing OUR Forebet -> HKJC files remain authoritative:

- data/team_alias_manual.csv
- data/team_alias_registry.csv
- data/team_alias_unresolved.csv

Multibetter's fast cache is:

- multibetter/data/forebet_bridge_aliases.csv

## Resolution order

### 1. EXACT / cached alias

Use the alias dictionary first. If both home and away resolve, match the exact fixture inside the DATE + TIME + LEAGUE bucket.

This is the hot path and should handle more and more traffic over time.

### 2. DETERMINISTIC UNIQUE FIXTURE

Only when the alias cache misses:

- normalize date
- normalize kickoff time
- normalize league
- retrieve only fixtures in that exact date/time/league bucket

If there is exactly one compatible fixture, it is deterministic enough to resolve the missing source names to that fixture's OUR Forebet home/away names.

The new mappings are written immediately to the alias cache with:

- status = AUTO_DETERMINISTIC
- confidence = 1.000
- reason = UNIQUE_DATE_TIME_LEAGUE_FIXTURE

### 3. DETERMINISTIC TEAM PAIR IN SMALL BUCKET

Some leagues have several fixtures at the same kickoff.

In that case, team-name comparison is allowed **only inside the small date/time/league candidate bucket**, never against the whole team universe.

A unique winner with a clear margin may be accepted and its missing aliases cached.

### 4. AMBIGUOUS / CONFLICT

Do not auto-write when:

- date/time/league bucket is missing
- two candidate fixtures remain too similar
- source alias conflicts with an existing cached target
- senior/youth/reserve/women team class conflicts

These cases go to candidate/review handling rather than being forced.

## Time is a strong identity field

Time is not merely a weak hint.

For automatic alias learning, the default rule uses **exact normalized kickoff time**. A one-hour or timezone tolerance may be useful during upstream source grouping, but it must not silently create a permanent alias in the cache.

If a timezone conversion is required, normalize the timezone first and then compare exact normalized times.

## Long-term effect

The alias table should become faster and more complete naturally:

```text
first encounter:
cache miss -> deterministic fixture resolution -> cache alias

later encounters:
cache hit -> direct resolution
```

Therefore the system spends computation mainly on genuinely new naming variants.

## Candidate evidence remains useful

The candidate table remains for ambiguous cases only. It is no longer the normal path for a deterministic unique fixture.

Fuzzy similarity by itself must never auto-write an alias.

## Conflict rules

Block automatic learning when:

- same source alias points to multiple OUR Forebet targets
- team class changes (senior/U21/U23/B/reserve/women)
- home/away orientation conflicts
- duplicate fixtures exist in the same exact identity bucket

## Health metrics

Track:

- cache-hit rate
- deterministic-learning rate
- ambiguous rate
- conflict count
- new aliases learned
- aliases reused
- candidate/review queue size

A healthy mature system should show cache-hit rate rising over time and deterministic-learning rate falling.

## Current Fast Tracker baseline

Audit on 2026-09-20:

- team_alias_registry.csv: 544 rows
- team_alias_manual.csv: 33 rows
- registry conflicts: 0
- manual conflicts: 0
- unresolved rows: 0


## Home / away orientation is part of the fixture key

The deterministic identity is treated as:

```text
DATE + exact normalized TIME + LEAGUE + HOME + AWAY
```

For sources with explicit HOME/AWAY fields, orientation is a hard rule:

- source HOME can only learn/match OUR Forebet HOME
- source AWAY can only learn/match OUR Forebet AWAY
- a cached alias that points to the opposite side is a conflict
- A vs B is not treated as the same oriented fixture as B vs A

For generic layouts that only expose left/team1 and right/team2:

- default assumption: left/team1 = HOME
- default assumption: right/team2 = AWAY
- mark the orientation as inferred rather than explicit
- if the reversed pairing is materially stronger, do not auto-learn a permanent alias from that observation

This makes home/away a low-cost matching signal and further reduces the need for broad fuzzy comparison.
