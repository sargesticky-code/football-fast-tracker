#!/usr/bin/env python3
"""Phase 3 Layer 1 diagnostic against the repo's HKJC live-odds snapshot."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from phase3.hkjc_authority import evaluate_authority

PATH = Path("data/hkjc_live_odds.csv")


def main() -> int:
    if not PATH.exists():
        print("PHASE3_LAYER1 NO_SNAPSHOT file_missing=1")
        return 2

    with PATH.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    fetched_values = [str(r.get("fetched_at_hkt") or "").strip() for r in rows]
    fetched_values = [x for x in fetched_values if x]
    fetched_at = max(fetched_values) if fetched_values else None

    result = evaluate_authority(
        rows,
        source_fetched_at=fetched_at,
        now=datetime.now(timezone.utc),
    )
    age = "NA" if result.snapshot_age_seconds is None else f"{result.snapshot_age_seconds:.1f}"
    print(
        "PHASE3_LAYER1 "
        f"health={result.health} "
        f"authority_usable={int(result.authority_usable)} "
        f"source_rows={result.source_rows} "
        f"eligible={result.eligible_rows} "
        f"identity_gap={result.identity_gap_rows} "
        f"not_selling={result.not_selling_rows} "
        f"not_live={result.not_live_rows} "
        f"stale_rows={result.stale_rows} "
        f"snapshot_age_seconds={age}"
    )
    for r in result.rows:
        print(
            "PHASE3_MATCH "
            f"event={r.get('phase3_hkjc_event_id') or '-'} "
            f"match={r.get('phase3_hkjc_match_id') or '-'} "
            f"status={r.get('phase3_match_status') or '-'} "
            f"selling={r.get('phase3_selling_status') or '-'} "
            f"eligible={int(bool(r.get('phase3_eligible')))} "
            f"reason={r.get('phase3_authority_reason')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
