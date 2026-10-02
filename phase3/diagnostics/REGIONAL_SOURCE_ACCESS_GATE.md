# Phase 3 regional live-source access gate

Checked 2026-10-02. This is a shadow-benchmark diagnostic only; it does not change production source priority, HKJC eligibility, or Heavy Lane cadence.

## Gate

A regional candidate is benchmarkable only when all of these are true:

1. Access is publicly documented or explicitly provisioned for API/widget use.
2. Rate limits/cadence are known enough to avoid aggressive polling or anti-bot bypass.
3. One request can cover multiple live matches where the provider supports it.
4. Persistent external IDs can be stored and verified against HKJC-authorised matches before the live heartbeat.
5. The adapter can expose request latency plus source/event timestamps when the provider supplies them.
6. No browser fan-out and no 5-second fuzzy rematching.

## Candidate status

| Candidate | Public/documented access evidence | Phase-3 status | Reason |
| --- | --- | --- | --- |
| TheSports | Public product pages advertise football live-score API/data feeds, JSON/WebSocket delivery, developer documentation and a trial | ELIGIBLE_FOR_CREDENTIALLED_SHADOW | Technically appropriate regional candidate once credentials are provisioned; must still be measured from the deployed backend region |
| Tipsme | Public partnership material says Tipsme uses TheSports LiveTrackerPro | NOT_A_DIRECT_API_CANDIDATE | Benchmark the documented upstream provider (TheSports), not reverse-engineer the Tipsme client |
| Leisu | Live-score consumer product is publicly visible, but no sufficiently clear public developer API/rate contract was verified in this review | HOLD_NO_SCRAPE | Do not reverse-engineer or aggressively poll consumer endpoints |
| SofaScore | Official site/widgets provide live data; existing Phase 3 shadow adapter remains shadow-only | EXISTING_SHADOW | Keep current bounded shadow protocol; no primary promotion from one-off latency |
| FotMob | Existing Phase 3 source code already uses bounded HTTP access for identity/heavy evidence | EXISTING_SHADOW | Keep fast benchmark isolated from Heavy Lane |

## Measurement rule

Regional geography is not latency evidence. TheSports (or any later Greater-China candidate) remains unmeasured until the same HKJC-authorised live-match window records repeated median/p95 network latency, source-data age, score/minute freshness, coverage, failure rate, persistent identity match rate, collision rows and exact upstream request count alongside at least one existing candidate.

If credentials are unavailable, report the candidate as **credential-blocked/unmeasured**, not faster or slower.

## Sources reviewed

- TheSports: https://www.thesports.com/ and https://www.thesports.com/solutions/data-feeds
- TheSports/Tipsme partnership: https://www.thesports.com/th/news/detail/68
- SofaScore widgets: https://corporate.sofascore.com/widgets

No undocumented Leisu endpoint is recorded here intentionally.
