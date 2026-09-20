# App V1 intelligence dashboard

The home screen is a review dashboard, not a betting-rank engine.

Default review priority combines:
- model/evidence coverage
- absolute model-vs-HKJC no-vig disagreement
- data freshness

It does **not** use realized ROI, hidden source weights, or a betting threshold.
Formal betting decisions remain gated by `private.source_registry.decision_enabled`
and the Phase 1 validation engine.

Operational freshness labels:
- fresh: <= 90 minutes
- aging: > 90 minutes and <= 6 hours
- stale: > 6 hours

Filters:
- 先睇: review priority
- 全部: kickoff order
- 分歧: largest absolute market/model disagreement
- 缺資料: HKJC selling match without external model evidence
- 過時: stale source data
