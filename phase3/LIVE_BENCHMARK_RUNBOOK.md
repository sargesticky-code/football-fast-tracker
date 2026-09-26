# Phase 3 live benchmark runbook

This runbook is Phase-3-only and shadow-only. It does not alter source priority or production Google Sheets.

## Same-window sampling

- Use only HKJC-eligible matches with persistent VERIFIED identity mappings.
- Sample at least two live sources in interleaved order across the same live-match window.
- Default evidence window: 3 rounds per source, with exact upstream request accounting.
- Prefer one upstream multi-match request per source/round when the source supports it.
- Do not fuzzy-rematch identities inside the fast heartbeat.

## Fast-lane evidence

Record per request: source, observed_at, source_updated_at when exposed, network_latency_ms, snapshot_age_seconds, score/minute/status freshness, mapped rows, unmapped rows, collision rows, request failure, and upstream request count.

Aggregate per source: median and p95 network latency, median and p95 source age, score/minute freshness, coverage, failure rate, and persistent identity match rate.

The benchmark remains shadow/fallback evidence. A one-off faster response is not sufficient to change the production primary.

## Heavy-lane isolation

Heavy fields (xG, shots, shots on target, possession, box touches, big chances, corners, events, momentum) remain on source-safe 30-60s+ cadence with separate timestamps and request-budget diagnostics. Preserve recent last-known-good heavy data across transient gaps. Never move heavy polling to the ~5s fast heartbeat.

## Regional-source gate

A Greater-China candidate may be added only when access is public/documented enough for the intended use, rate-safe, technically stable, and identity-safe. Geography is not latency evidence. Compare it from the deployed backend region using the same-window metrics above.

## Exit evidence

Do not select a new primary unless at least two sources have comparable same-window live observations and the candidate is measurably better on latency/freshness without unacceptable coverage, failure, or identity regressions. Otherwise retain it as shadow/fallback and document the result.
