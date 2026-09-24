# SofaScore H2H adapter

Phase 1 now has a conservative SofaScore adapter in `scripts/sofascore_h2h.py`.

## Why this exists

HKJC remains the canonical fixture and betting authority, but its public result
history is too shallow to be the sole head-to-head source. SofaScore is used as
an enrichment source for deeper H2H history after identity has been verified.

## Source pattern

The adapter follows public endpoint patterns used by established community
projects such as `probberechts/soccerdata` and public SofaScore API references:

- `sport/football/scheduled-events/{YYYY-MM-DD}` — event discovery
- `event/{eventId}` — event identity/details
- `event/{eventId}/h2h/events` — direct meeting history

The implementation uses ordinary HTTP requests only. It does not contain WAF
bypass, browser impersonation, proxy rotation, or anti-bot evasion logic.

## Identity safety

A SofaScore event is promoted only when:

1. HKJC already supplies the canonical fixture.
2. Home and away names match exactly after conservative formatting
   normalization, or match an already VERIFIED SofaScore alias.
3. Kickoff time is inside a narrow tolerance window.
4. Exactly one SofaScore candidate survives.

Ambiguous or unmatched candidates stay unresolved. Cohort markers such as
`Women`, `U21`, `Reserve`, `B`, etc. are intentionally preserved.

Successful mappings should be persisted into the one-for-all identity master:

- source = `SOFASCORE`
- source team id
- source display name
- HKJC canonical team
- verified fixture/event evidence
- first/last seen timestamps

Once persisted, future jobs should reuse the mapping rather than fuzzy-match
the same team again.

## H2H normalization

`normalize_h2h_events()` accepts SofaScore's direct meetings and rewrites each
historical score into the orientation of the current HKJC fixture. This makes
`H`, `D`, `A`, goals and averages consistent even when the older match had the
teams reversed home/away.

The current output states are:

- `H2H_OK` — at least one verified direct meeting
- `NO_HISTORY` — verified source mapping but no prior direct meeting returned
- source/mapping failures are handled separately and must not be relabelled as
  `NO_HISTORY`

## Production rollout

Do not wire this adapter into a high-frequency live loop. H2H is slow-changing
prematch evidence. The intended next production step is:

1. discover current HKJC fixtures against SofaScore daily schedules;
2. persist unique verified SofaScore team/event IDs;
3. fetch H2H only for newly mapped or stale fixtures;
4. merge up to the latest five direct meetings into `match_h2h_current`;
5. expose full meetings only on `app-match-detail`, not the lightweight list
   feed.
