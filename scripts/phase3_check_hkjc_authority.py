#!/usr/bin/env python3
"""Phase 3 Layer 1 diagnostic against the freshest repo HKJC snapshot.

Prefer the dedicated live-odds snapshot when it has data. Fall back to the
normal HKJC current snapshot so Layer 1 can still prove freshness/fail-closed
semantics when there are no rows in hkjc_live_odds.csv.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from phase3.hkjc_authority import evaluate_authority

PATHS = (
    Path("data/hkjc_live_odds.csv"),
    Path("data/hkjc_current.csv"),
)


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _fetched_at(row: dict[str, str]) -> str:
    return str(
        row.get("fetched_at_hkt")
        or row.get("fetched_at")
        or row.get("source_fetched_at")
        or ""
    ).strip()


def _normalize(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    # hkjc_current.csv stores the already-normalized selling flag separately.
    # Convert it into the authority contract's explicit HKJC status without
    # allowing a truthy third-party field to create eligibility.
    if not (out.get("selling_status") or out.get("sellingStatus") or out.get("pool_status")):
        selling = str(out.get("selling") or "").strip().lower()
        if selling in {"1", "true", "yes"}:
            out["selling_status"] = "SELLINGSTARTED"
        elif selling in {"0", "false", "no"}:
            out["selling_status"] = "SELLINGSTOPPED"
    return out


def _choose_snapshot() -> tuple[Path | None, list[dict[str, str]], str | None]:
    candidates: list[tuple[str, int, Path, list[dict[str, str]]]] = []
    for priority, path in enumerate(PATHS):
        rows = _read(path)
        fetched = max((_fetched_at(r) for r in rows), default="")
        if rows and fetched:
            # ISO timestamps sort chronologically when emitted consistently.
            candidates.append((fetched, -priority, path, rows))
    if not candidates:
        return None, [], None
    fetched, _priority, path, rows = max(candidates, key=lambda x: (x[0], x[1]))
    return path, [_normalize(r) for r in rows], fetched


def main() -> int:
    path, rows, fetched_at = _choose_snapshot()
    if path is None:
        print("PHASE3_LAYER1 health=NO_SNAPSHOT authority_usable=0 source_rows=0")
        return 2

    result = evaluate_authority(
        rows,
        source_fetched_at=fetched_at,
        now=datetime.now(timezone.utc),
    )
    age = "NA" if result.snapshot_age_seconds is None else f"{result.snapshot_age_seconds:.1f}"
    print(
        "PHASE3_LAYER1 "
        f"source={path.as_posix()} "
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
        if r.get("phase3_eligible") or r.get("phase3_authority_reason") in {"IDENTITY_GAP", "STALE_AUTHORITY"}:
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
