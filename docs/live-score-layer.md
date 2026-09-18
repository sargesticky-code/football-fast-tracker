# Live Score Layer

This layer is deliberately independent from HKJC rapid polling.

## Endpoint

After Vercel deployment:

- JSON: `/api/live_scores`
- CSV: `/api/live_scores?format=csv`

## Providers

1. Football Live API (FotMob-backed) — primary
2. SportScore — fallback only when the primary cannot match a HKJC fixture

HKJC `data/hkjc_current.csv` is used only as the canonical fixture identity list.
The live endpoint never calls HKJC.

## Match policy

- Candidate HKJC fixtures: kickoff from 4 hours ago to 45 minutes ahead.
- Name matching strips age-group aliases such as HKJC `AM` vs provider `U23`.
- Provider kickoff must be within 120 minutes when available.
- Low-confidence and ambiguous matches are suppressed.
- Returned rows always carry `hkjc_event_id`, allowing the Google Sheet to XLOOKUP without re-matching Chinese team names.

## Refresh

Football Live API itself caches live data around 30 seconds, so requesting more frequently than 30 seconds normally produces no extra freshness.
The Vercel endpoint uses a short 15-second CDN cache to avoid duplicate upstream work.

SportScore attribution must be preserved if its data is displayed publicly:
`Powered by SportScore — https://sportscore.com/`


## Deploy

The repository is Vercel-ready through `vercel.json`.

Deploy/import:
https://vercel.com/new/clone?repository-url=https://github.com/sargesticky-code/football-fast-tracker

After deployment, use:
`https://<project>.vercel.app/api/live_scores?format=csv`

Paste that CSV endpoint into `LiveScoreFeed!B1` in Fast Tracker.


## Safe full-stat capture

The live endpoint reuses one FotMob `matchDetails` payload per selected live match to capture every available two-sided team stat dynamically, plus live events and momentum. With `?include=full`, the same payload also exposes shot map, lineup and match facts.

Safety policy:
- Only HKJC-targeted live fixtures are considered.
- One FotMob live-list request per endpoint refresh.
- At most 8 `matchDetails` requests per refresh.
- If more than 8 live matches exist, detail requests rotate across successive minutes.
- HTTP 403/429 stops further heavy detail calls immediately for that refresh.
- Vercel response caching is 55s with stale-while-revalidate 65s.
- CSV stays compact; heavy nested data is returned only in JSON.
- No paid API key is used.

Verified on 2026-09-18 with FB5390: one detail response yielded 86 team-stat entries, 33 momentum points, plus shot-map data.
