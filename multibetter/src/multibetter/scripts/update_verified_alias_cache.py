from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

from multibetter.aliasing.cache import AliasCacheRow, merge_learned_aliases
from multibetter.matching.fixture_resolver import LearnedAlias


FIELDS = [
    "github_forebet_alias",
    "our_forebet_name",
    "status",
    "confidence",
    "first_seen",
    "last_seen",
    "observation_count",
    "note",
]


def read_cache(path: Path) -> list[AliasCacheRow]:
    if not path.exists():
        return []

    rows: list[AliasCacheRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            alias = (row.get("github_forebet_alias") or "").strip()
            target = (row.get("our_forebet_name") or "").strip()
            if not alias or not target:
                continue
            rows.append(
                AliasCacheRow(
                    alias=alias,
                    target=target,
                    status=(row.get("status") or "VERIFIED").strip(),
                    confidence=float(row.get("confidence") or 1.0),
                    first_seen=(row.get("first_seen") or "").strip(),
                    last_seen=(row.get("last_seen") or "").strip(),
                    observation_count=int(row.get("observation_count") or 1),
                    note=(row.get("note") or "").strip(),
                )
            )
    return rows


def read_learned(path: Path) -> list[tuple[LearnedAlias, datetime]]:
    rows: list[tuple[LearnedAlias, datetime]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            alias = (row.get("github_forebet_alias") or "").strip()
            target = (row.get("our_forebet_name") or "").strip()
            if not alias or not target:
                continue
            observed_at = datetime.fromisoformat(row["observed_at"])
            rows.append(
                (
                    LearnedAlias(
                        alias=alias,
                        target=target,
                        reason=(row.get("reason") or "DETERMINISTIC_FIXTURE").strip(),
                        confidence=float(row.get("confidence") or 1.0),
                    ),
                    observed_at,
                )
            )
    return rows


def write_cache(path: Path, rows: list[AliasCacheRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "github_forebet_alias": row.alias,
                    "our_forebet_name": row.target,
                    "status": row.status,
                    "confidence": f"{row.confidence:.3f}",
                    "first_seen": row.first_seen,
                    "last_seen": row.last_seen,
                    "observation_count": row.observation_count,
                    "note": row.note,
                }
            )


def apply_learned_file(
    cache_rows: list[AliasCacheRow],
    learned_rows: list[tuple[LearnedAlias, datetime]],
) -> list[AliasCacheRow]:
    state = tuple(cache_rows)
    for learned, observed_at in learned_rows:
        state = merge_learned_aliases(
            state,
            [learned],
            observed_at=observed_at,
        )
    return list(state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--learned", type=Path, required=True)
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("multibetter/data/forebet_bridge_aliases.csv"),
    )
    args = parser.parse_args()

    cache = read_cache(args.cache)
    learned = read_learned(args.learned)
    merged = apply_learned_file(cache, learned)
    write_cache(args.cache, merged)


if __name__ == "__main__":
    main()
