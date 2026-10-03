# Shadow benchmark source-age field audit

Phase-3-only diagnostic. No production source, Google Sheet, Phase 1/2, or Heavy Lane behavior is changed.

## Finding

At branch head `938ec00ea8909a9ab4c6382cfa2e0b4336e93122`, the same-window evidence contract and shadow summary use different names for the same source-derived age metric:

- `source_benchmark_evidence.py` requires `median_source_age_seconds` and `p95_source_age_seconds`.
- `source_shadow_runner.py` currently emits `median_snapshot_age_seconds` and `p95_snapshot_age_seconds`.
- Both runner values are derived from provider `source_updated_at`; no additional upstream request is needed to satisfy the contract.

## Required correction

The runner should emit the required `median_source_age_seconds` / `p95_source_age_seconds` fields from the existing age samples. The snapshot-age names may remain as compatibility aliases. A regression should pass the runner summary directly to `validate_same_window_report` so future field drift fails closed.

Until that correction is committed and tested, a real same-window report produced by the runner can be rejected as incomplete even when source age was measured. Do not interpret that validation failure as source latency/freshness evidence.

## Benchmark status

No upstream source request was made for this audit. It therefore creates no FotMob/SofaScore latency, freshness, coverage, failure-rate, or identity measurement and makes no source-selection decision.
