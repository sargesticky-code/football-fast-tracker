# Multibetter V1 — Architecture, Matching Mechanism, Handoff & Operating Rules

> **Purpose of this README**
>
> This file is the primary handoff / source-of-truth for future ChatGPT work on Multibetter V1.
> Read this file before changing matching, aliasing, current-output generation, or Fast Tracker integration.
> The hidden Google Sheet tab `AI Multibetter Notes` is only a short pointer/summary; this README is the detailed specification.

---

## 1. Project boundary

Multibetter is an experimental multi-source football prediction framework developed **separately** from the existing Fast Tracker production system.

### Non-negotiable boundary

- Fast Tracker production stays on GitHub branch `main`.
- Multibetter development stays on branch `multibetter-v1`.
- Multibetter code lives under `multibetter/`.
- Do **not** change Fast Tracker production feeds, formulas, Dashboard Board, or existing production aliases merely to make Multibetter easier.
- Only port a Multibetter component back to Fast Tracker after it has been proven stable and the user explicitly wants that integration.

Repository:

```text
sargesticky-code/football-fast-tracker
```

Multibetter branch:

```text
multibetter-v1
```

Primary path:

```text
multibetter/
```

---

## 2. Production authority hierarchy

The identity chain is:

```text
External multi-source predictions
        ↓
GitHub multi-source fixture
        ↓
GitHub Forebet identity
        ↓
Multibetter GitHub-Forebet → OUR-Forebet bridge/cache
        ↓
OUR Forebet identity
        ↓
Existing Fast Tracker Forebet ↔ HKJC alias layer
        ↓
HKJC event ID
        ↓
HKJC names / odds / display authority
```

### What each layer means

- **HKJC** is the final event, price and display authority.
- **OUR Forebet** is the existing Fast Tracker Forebet identity already linked to HKJC.
- **GitHub Forebet** is the Forebet identity from the external multi-source project.
- **Other sources** should not each build their own HKJC alias system.
- New sources should first be grouped around the external framework's Forebet fixture, then use the one Forebet bridge into our system.

This single-bridge architecture exists to avoid repeating team alias work for APWin / BetClan / Statarea / Prematips / FootballSuperTips / future sources.

---

## 3. External multi-source framework currently studied

Reference project:

```text
Ezee-Kits/SPORTYBET-AUTO-TRADING-BOT
```

Observed standardized sources:

```text
ACC  = Accumulator Generator
BCL  = BetClan
FST  = FootballSuperTips
FRB  = Forebet
PRE  = Prematips
STA  = Statarea
```

Its original weighting:

```python
ACC = 0.8
BCL = 1.0
FST = 0.9
FRB = 1.4
PRE = 1.1
STA = 1.2
```

These weights are preserved only as the upstream V1 baseline. They are **not** assumed to be optimal. Long-term Multibetter weights should be market-specific and empirically calibrated.

The upstream project originally uses a generic matcher based on:

- home-team similarity
- away-team similarity
- time equal to target or ±1 hour
- SequenceMatcher threshold around 55%

Multibetter reuses that idea only for **upstream source grouping around GitHub Forebet**. It does not allow that broad fuzzy logic to become the permanent GitHub-Forebet → OUR-Forebet identity system.

---

## 4. The key matching design: cache first, deterministic fallback

The user explicitly chose the following mechanism because it reduces computation over time.

### Production order

```text
1. Alias/exact cache lookup
        ↓ cache miss
2. Exact normalized DATE
3. Exact normalized TIME
4. LEAGUE / competition if available
5. HOME / AWAY orientation
6. Compare team1/team2 only inside that tiny fixture bucket
        ↓ unique match
7. Accept fixture
8. Learn missing aliases once
9. Write aliases back into fast cache
10. Later occurrences use cache directly
```

This is a **learn-once / reuse-many-times** system.

The deterministic fixture resolver is the expensive path only for genuinely new naming variants. Mature operation should increasingly become dictionary lookup rather than repeated fuzzy computation.

---

## 5. Fixture identity fields

The strongest intended identity is:

```text
DATE + exact normalized TIME + LEAGUE + HOME + AWAY
```

### Date

Normalize supported source date formats before comparing.

Examples already observed:

```text
2026-02-18
18/02/2026
18/02/26
2026.18.02
2026-2-18
```

### Time

Time matters strongly.

For **permanent alias learning**, use exact normalized kickoff time after timezone normalization.

Do not permanently learn an alias merely because a source row is within ±1 hour.

The ±1 hour rule belongs to the upstream source-grouping stage only, because source websites can expose different timezone conventions.

Once the source time has been normalized to the same timezone/reference as our Forebet fixture, permanent alias learning should compare exact time.

### League / competition

League is a strong discriminator and should be used whenever the source provides it.

If league is missing from the external source snapshot:

```text
DATE + exact TIME
        ↓
small candidate bucket
        ↓
HOME/AWAY + team pair
```

This is still far cheaper and safer than global team-name fuzzy matching.

### Home / away

Home/away is part of fixture identity.

For sources with explicit fields:

```text
HOME TEAM = hard home role
AWAY TEAM = hard away role
```

For generic left/right or team1/team2 layouts:

```text
left / team1  → assume HOME
right / team2 → assume AWAY
```

Mark this as inferred rather than explicit.

Important rule:

```text
A vs B != B vs A
```

A cached alias pointing to the opposite side is a conflict, not a valid match.

If the reversed pairing is materially stronger than the direct home/away pairing, do not auto-learn a permanent alias from that observation.

---

## 6. Fast alias cache

Fast cache file:

```text
multibetter/data/forebet_bridge_aliases.csv
```

Current schema:

```text
github_forebet_alias
our_forebet_name
status
confidence
first_seen
last_seen
observation_count
note
```

### Cache lookup rules

1. Exact OUR-Forebet name match wins immediately.
2. Otherwise use verified/deterministic alias cache.
3. If both home and away resolve, locate the fixture inside the exact date/time/league bucket.
4. Do not run a global fuzzy search when cache already resolves the identity.

### Cache update rules

When a deterministic fixture uniquely resolves a new naming variant:

```text
status = AUTO_DETERMINISTIC
confidence = 1.000
note = reason that proved the fixture
```

The cache is updated immediately in memory during the same build run, so later fixtures in that run can already reuse the newly learned alias.

Cache hits update:

- last_seen
- observation_count

This allows future 30/90-day usage health reporting.

### Conflict rule

Never silently overwrite:

```text
same alias -> existing target A
same alias -> newly inferred target B
```

This must become a conflict/review condition.

---

## 7. Deterministic cold-path resolver

Implemented in:

```text
multibetter/src/multibetter/matching/fixture_resolver.py
```

Important statuses:

```text
FAST_ALIAS
DETERMINISTIC_UNIQUE
DETERMINISTIC_TEAM_PAIR
AMBIGUOUS
NO_FIXTURE
CONFLICT
```

### Cold path A — unique date/time/league fixture

If the exact date/time/league bucket contains only one compatible fixture and home/away orientation is safe, the source names can be learned against that fixture.

### Cold path B — multiple simultaneous fixtures

If several fixtures share the same kickoff:

- compare source home only to candidate home
- compare source away only to candidate away
- stay inside this small bucket
- require a clearly unique winner
- do not scan all global teams

### Never auto-learn when

- no date/time bucket exists
- multiple fixtures remain too similar
- home/away appears reversed
- alias conflicts with existing target
- team class conflicts
- duplicate exact fixture identities exist

---

## 8. Team-class safety

Never learn across incompatible team classes.

Examples:

```text
Arsenal U21 != Arsenal
Sevilla II != Sevilla
Getafe B != Getafe
Chelsea Women != Chelsea senior
Reserve != senior
Youth != senior
```

Supported team classes include:

```text
SENIOR
WOMEN
YOUTH
RESERVE
B_TEAM
UNKNOWN
```

Wrong class should be rejected/conflicted even when names are highly similar.

---

## 9. Candidate / review queue

Ambiguous cases should not be forced.

Candidate file:

```text
multibetter/data/forebet_bridge_candidates.csv
```

It can retain:

- proposed alias
- target
- first_seen
- last_seen
- observation_count
- best/latest similarity
- distinct opponents
- event IDs
- status
- reason

Important distinction:

- **deterministic unique fixture** may auto-write the fast alias cache.
- **fuzzy/ambiguous evidence alone** must not auto-write a production alias.

Candidate/review handling exists for the exceptional cases that deterministic fixture identity cannot resolve safely.

---

## 10. Existing Fast Tracker Forebet ↔ HKJC aliases remain authoritative

Do not replace the production Fast Tracker alias system.

Existing production files on `main`:

```text
data/team_alias_manual.csv
data/team_alias_registry.csv
data/team_alias_unresolved.csv
```

Audit snapshot on 2026-09-20:

```text
team_alias_registry.csv = 544 rows
team_alias_manual.csv   = 33 rows
registry conflicts      = 0
manual conflicts        = 0
unresolved rows         = 0
```

This is a healthy baseline.

Multibetter should only maintain the small bridge between GitHub Forebet naming and OUR Forebet naming.

---

## 11. Upstream source grouping around GitHub Forebet

Implemented in:

```text
multibetter/src/multibetter/sources/github_multi.py
```

Input source CSV names expected by V1:

```text
forebet.csv              required anchor
accumulator.csv          optional
betclan.csv              optional
footballsupertips.csv    optional
prematips.csv            optional
statarea.csv             optional
```

The grouping layer:

1. takes each GitHub Forebet row as the anchor;
2. finds matching rows from the optional upstream sources;
3. records source match similarity / quality;
4. builds one `MultiSourceFixture`.

### Upstream match quality metadata

Current quality labels:

```text
HIGH   >= 85 similarity
GOOD   >= 75
REVIEW < 75
```

The upstream discovery threshold can remain low enough to preserve known naming variants, but REVIEW-grade source rows need not be included in high-confidence consensus.

---

## 12. Historical validation already performed

Historical sample used:

```text
2026-02-18
```

Input row counts:

```text
ACC 60
BCL 54
FST 44
FRB 106
PRE 50
STA 54
```

Valid Forebet anchors:

```text
105
```

Observed grouping:

```text
Forebet + >=1 additional source: 58 / 105 = 55.2%
4+ sources:                     30 / 105
all 6 sources:                  17 / 105
duplicate reuse of a source row: 0 observed
```

Median team-pair similarity of matched source rows:

```text
ACC 91.9%
BCL 90.0%
FST 93.5%
PRE 91.2%
STA 90.0%
```

This validation supports the architecture but should not be confused with current/live coverage.

Historical documentation:

```text
multibetter/docs/historical_grouping_validation_2026-02-18.md
multibetter/samples/grouped_consensus_2026-02-18.csv
```

---

## 13. GitHub-Forebet → OUR-Forebet compatibility validation

Historical comparison found that, among overlapping observed Forebet team names, the overlap was exact in the sampled data.

Important interpretation:

- GitHub Forebet and OUR Forebet both originate from Forebet.
- Therefore exact identity should be common.
- Non-overlap does not automatically mean mismatch; OUR Forebet universe is HKJC-driven and may simply not have encountered those teams yet.
- The bridge alias table should remain small and exception-oriented.

Validation document:

```text
multibetter/docs/forebet_bridge_validation.md
```

---

## 14. Consensus engine

Implemented in:

```text
multibetter/src/multibetter/consensus/engine.py
```

Current V1 markets:

```text
HDA
GOALS
BTTS
CORNERS  (framework enum exists; current upstream six-source CSVs do not consistently supply it)
```

Current builder emits, when available:

```text
consensus_home
consensus_draw
consensus_away
consensus_over25
consensus_under25
consensus_btts_yes
consensus_btts_no
```

REVIEW-grade source matches should not automatically enter high-confidence consensus.

Long term:

- calibrate weights by source + market
- do not keep one global source quality score
- validate against historical outcomes before treating weights as meaningful

---

## 15. Current build pipeline

Main builder:

```text
multibetter/src/multibetter/pipeline/current.py
```

CLI:

```text
multibetter/src/multibetter/scripts/build_current.py
```

Run shape:

```bash
python -m multibetter.scripts.build_current \
  --source-dir multibetter/incoming/current
```

The builder:

1. reads OUR current Forebet feed;
2. loads current GitHub multi-source CSVs;
3. loads alias cache;
4. groups sources around each GitHub Forebet anchor;
5. resolves each fixture cache-first;
6. deterministic-matches only cache misses;
7. immediately learns safe new aliases;
8. reuses those aliases in the same run;
9. updates cache usage metadata;
10. computes consensus;
11. writes current output;
12. writes health output.

Primary output:

```text
multibetter/data/multibetter_current.csv
```

Health output:

```text
multibetter/data/multibetter_current_health.json
```

Alias health:

```text
multibetter/data/alias_health.json
```

---

## 16. Manual GitHub workflow

Workflow:

```text
.github/workflows/multibetter_v1_build.yml
```

It is intentionally manual / branch-only for now.

It:

1. checks out `multibetter-v1`;
2. installs Multibetter;
3. runs tests;
4. validates that current `forebet.csv` input exists;
5. builds current output;
6. runs alias health audit;
7. commits only Multibetter output files if changed.

### Why no cron yet

Do not enable scheduled production runs until a live current multi-source collector is connected.

A scheduled workflow must not overwrite a last-good output with empty/missing current input.

---

## 17. Alias health / audit

Health script:

```text
multibetter/scripts/alias_health_report.py
```

Long-term metrics to track:

```text
cache-hit rate
deterministic-learning rate
ambiguous rate
conflict count
new aliases learned
aliases reused
candidate/review queue size
exact bridge rate
unresolved rate
```

Desired mature behavior:

```text
cache-hit rate ↑
deterministic-learning rate ↓
ambiguous/conflict rate → near zero
global fuzzy matching → near zero
```

---

## 18. Google Sheet production context

Production spreadsheet:

```text
Fast Tracker
Spreadsheet ID:
1lUQT4UojtwDxZl2xqYgR3P8hCgOMBpyDQDi5abe0cjQ
```

### Critical safety rule

**Do not clear, rebuild, or redesign `Dashboard Board` unless the user explicitly asks.**

A previous redesign accidentally cleared this production dashboard and it had to be restored from snapshot. Do not repeat that failure.

Important production tabs include:

```text
Dashboard Board
Fast Tracker Live
ForebetFeed
HKJCFeed
ModelFeed
FormFeed
OddsMovementFeed
LiveScoreFeed
APWinFeed
ForebetSupplementFeed
HKJCLiveOddsFeed
TeamFormFeed
System Health
Team Alias Registry
```

The hidden tab:

```text
AI Multibetter Notes
```

contains a concise future-assistant handoff and points back to this README.

---

## 19. Fast Tracker data rules that Multibetter must respect

Stable project rules:

- HKJC event ID remains final event identity.
- HKJC names remain final display names.
- Every HKJC match should be representable even when another source has NO DATA.
- Finished matches should not appear in upcoming/live display.
- Raw capture horizon is approximately +48 hours.
- Display/decision horizon is approximately +24 hours.
- STALE detection is required.
- Never present stale HKJC prices as current.
- Raw capture and decision/display layers should remain separated.
- Prefer last-good data over blanking a feed on a temporary source failure.
- Report exceptions instead of forcing bad matches.

---

## 20. Current/known source-health lessons from Fast Tracker

These are operational lessons, not permanent live status.

- Large volatile formulas and duplicated hidden formulas previously caused refresh lock failures.
- Heavy `NOW()` dependencies were reduced; controlled health timestamps are preferred.
- Hidden detail calculations should not duplicate thousands of formulas unnecessarily.
- A source failure should be isolated instead of blanking unrelated data.
- Current source ingestion must preserve last-good snapshots where practical.

---

## 21. Match-detail link issue outside Multibetter

There is a known Fast Tracker UI issue where match-detail links can race against a dynamically sorted helper range.

The long-term fix should use stable event-ID → block mapping rather than position-dependent dynamic sort matching.

Do not reintroduce wildcard MATCH as a quick fix.

This issue is adjacent to, but not part of, the Multibetter identity mechanism.

---

## 22. APWin status

An APWin V2 collector prototype exists in the branch.

However:

- the studied public multi-source GitHub project currently does not include APWin;
- APWin should not become a separate APWin→HKJC alias system;
- if APWin is added, preferred design is to incorporate it into the multi-source fixture layer or map it into GitHub Forebet first.

APWin source code:

```text
multibetter/src/multibetter/sources/apwin.py
```

---

## 23. Source statuses / failure isolation

Use explicit source states rather than vague CHECK values.

Useful statuses:

```text
OK
STALE
FETCH_ERROR
PARSER_ERROR
BLOCKED
NO_MATCH
AMBIGUOUS_MATCH
```

Important principle:

```text
NO DATA is safer than WRONG DATA
```

A failed source should not erase or invalidate other healthy source rows for the same fixture.

---

## 24. What future ChatGPT should do first

When resuming this project:

1. Read this README completely.
2. Confirm work is on `multibetter-v1`, not production `main`.
3. Read the hidden Google Sheet tab `AI Multibetter Notes` if available.
4. Inspect current alias health before changing matcher behavior.
5. Preserve cache-first matching.
6. Preserve exact time + league + home/away deterministic fallback.
7. Do not expand global fuzzy matching.
8. Do not build source-specific HKJC alias systems.
9. Do not touch `Dashboard Board` unless explicitly requested.
10. Run tests before changing persistent alias-learning logic.
11. If adding a source, group it to GitHub Forebet first.
12. If current collector input is not live/complete, do not enable cron.
13. If a proposed alias is ambiguous, keep it unresolved/review instead of forcing it.
14. Keep last-good outputs rather than writing empty current outputs.

---

## 25. Key code map

```text
multibetter/src/multibetter/models.py
    Core data models.

multibetter/src/multibetter/sources/github_multi.py
    Groups external source rows around GitHub Forebet.

multibetter/src/multibetter/matching/fixture_resolver.py
    Cache-first deterministic fixture resolver.

multibetter/src/multibetter/matching/forebet_bridge.py
    Exact/verified Forebet-name bridge helper.

multibetter/src/multibetter/aliasing/cache.py
    Alias cache merge + usage metadata.

multibetter/src/multibetter/aliasing/registry.py
    Candidate evidence / audit helpers.

multibetter/src/multibetter/consensus/engine.py
    Weighted market consensus.

multibetter/src/multibetter/pipeline/current.py
    End-to-end current builder.

multibetter/src/multibetter/scripts/build_current.py
    CLI entry point.

multibetter/src/multibetter/scripts/update_verified_alias_cache.py
    Persistent cache updater.

multibetter/scripts/alias_health_report.py
    Alias audit / health report.

multibetter/tests/
    Regression tests. Matching/alias changes must add/update tests.
```

---

## 26. Current design philosophy

The core philosophy is:

```text
Use cheap exact knowledge first.
Use fixture context only when exact knowledge is missing.
Learn a safe result once.
Cache it.
Do not recompute it forever.
Do not guess when the fixture is not unique.
```

The alias table is therefore not just a static list. It is a **fast identity cache** that becomes more useful over time.

The deterministic fixture key is the **cache-miss learning engine**.

The final intended steady state is:

```text
Most fixtures: alias/exact cache hit
Few fixtures: deterministic fallback for genuinely new variants
Very few fixtures: ambiguous/review
Zero desired: silent wrong matches
```

---

## 27. Next major milestone

The next major engineering milestone is **live current multi-source intake**.

Needed:

```text
forebet.csv
accumulator.csv
betclan.csv
footballsupertips.csv
prematips.csv
statarea.csv
```

Once current intake is reliable:

1. run end-to-end current build;
2. verify alias learning;
3. verify no blank overwrite behavior;
4. verify source health;
5. only then consider scheduled automation;
6. only after stable outputs consider a separate Multibetter Google Sheet/dashboard.

Dashboard work is not the first priority. Identity and source reliability come first.

---

## 28. Final rule summary

```text
HKJC = final event/display/price authority
OUR Forebet = existing bridge to HKJC
GitHub Forebet = external multi-source identity anchor

Match:
alias cache first
→ exact date
→ exact normalized time
→ league if available
→ home/team1 = home
→ away/team2 = away
→ compare only within tiny candidate bucket
→ unique match
→ learn alias once
→ reuse cache thereafter

Never:
global fuzzy matching as primary identity
source-by-source HKJC alias systems
home/away reversal auto-learning
team-class cross-learning
silent alias overwrite
blank production output because one source failed
unapproved Dashboard Board rebuild
```
