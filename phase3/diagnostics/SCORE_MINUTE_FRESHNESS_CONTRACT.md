# Score and minute freshness benchmark contract

Phase 3 shadow benchmarking must measure score freshness and match-minute freshness separately from transport latency and generic source snapshot age.

For each successful candidate snapshot, record these optional source timestamps when the provider exposes them:

- `score_updated_at`: provider timestamp for the score state represented by the snapshot
- `minute_updated_at`: provider timestamp for the match clock/minute state represented by the snapshot

Derive `score_age_seconds` and `minute_age_seconds` at the same `observed_at` clock used for snapshot-age measurement. Aggregate median and p95 values per source over the same bounded live-match window.

If a provider does not expose a trustworthy score or minute update timestamp, report the corresponding freshness metric as unavailable. Do not substitute network latency, local receipt time, or a guessed event time.

This evidence is independent of coverage and identity evidence. HKJC remains the eligibility authority; only persistently VERIFIED identities are benchmarked. No fuzzy rematching is allowed in the fast loop, and freshness measurement must not add an upstream request.

A candidate cannot be promoted from shadow status merely because network latency is lower. Production-primary selection requires same-window evidence for latency, source/snapshot age, score/minute freshness, coverage, failures, and identity safety.
