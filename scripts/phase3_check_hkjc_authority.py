#!/usr/bin/env python3
"""Phase 3 Layer 1 authority diagnostic.

Prefer the dedicated Phase 3 JSON authority snapshot because it carries an
explicit fetch timestamp even when HKJC currently has zero live rows. Fall
back to legacy repository CSV snapshots only for compatibility.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from phase3.hkjc_authority import evaluate_authority

JSON_PATH = Path("data/phase3_hkjc_authority.json")
CSV_PATHS = (
    Path("data/hkjc_live_odds.csv"),
    Path("data/hkjc_current.csv"),
)


def _read_csv(path: Path) -> list[dict[str, str]]:
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
    if not (out.get("selling_status") or out.get("sellingStatus") or out.get("pool_status")):
        selling = str(out.get("selling") or "").strip().lower()
        if selling in {"1", "true", "yes"}:
            out["selling_status"] = "SELLINGSTARTED"
        elif selling in {"0", "false", "no"}:
            out["selling_status"] = "SELLINGSTOPPED"
    return out


def _choose_snapshot() -> tuple[str | None, list[dict], str | None]:
    if JSON_PATH.exists():
        try:
            payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            fetched = str(payload.get("fetched_at") or "").strip()
            rows = payload.get("rows") or []
            if fetched and isinstance(rows, list):
                return JSON_PATH.as_posix(), [_normalize(dict(r)) for r in rows], fetched
        except (OSError, ValueError, TypeError):
            pass

    candidates: list[tuple[str, int, Path, list[dict[str, str]]]] = []
    for priority, path in enumerate(CSV_PATHS):
        rows = _read_csv(path)
        fetched = max((_fetched_at(r) for r in rows), default="")
        if rows and fetched:
            candidates.append((fetched, -priority, path, rows))
    if not candidates:
        return None, [], None

    fetched, _priority, path, rows = max(candidates, key=lambda x: (x[0], x[1]))
    return path.as_posix(), [_normalize(r) for r in rows], fetched


def main() -> int:
    source, rows, fetched_at = _choose_snapshot()
    result = evaluate_authority(
        rows,
        source_fetched_at=fetched_at,
        now=datetime.now(timezone.utc),
    )

    age = "NA" if result.snapshot_age_seconds is None else f"{result.snapshot_age_seconds:.1f}"
    print(
        "PHASE3_LAYER1 "
        f"source={source or '-'} "
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

    # Non-zero only when the authority source itself is unusable. Fresh zero-live
    # rows are a valid state and must not be mistaken for capture failure.
    return 0 if result.authority_usable else 2


if __name__ == "__main__":
    raise SystemExit(main())
