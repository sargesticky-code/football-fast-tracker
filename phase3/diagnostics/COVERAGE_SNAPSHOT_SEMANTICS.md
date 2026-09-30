# Phase 3 shadow coverage semantics

Coverage must be measured per successful live snapshot, not by summing VERIFIED rows across repeated benchmark rounds. Repeated observations of the same HKJC-authorised match must not inflate coverage.

For each source and successful snapshot:

`coverage = min(verified_mapped_rows, hkjc_eligible_rows) / hkjc_eligible_rows`

Report median (and, where useful, p95) snapshot coverage across the same benchmark window. Keep aggregate mapped/unmapped/collision row counts as request-volume diagnostics only; do not use their sums as the coverage numerator.

HKJC remains the eligibility authority. Identity must already be persistently VERIFIED; this benchmark does not fuzzy-rematch. Shadow evidence must never promote a production primary automatically.
