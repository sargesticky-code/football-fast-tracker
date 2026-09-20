from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from multibetter.pipeline.current import (
    build_current,
    load_source_tables,
    read_csv_rows,
)
from multibetter.scripts.update_verified_alias_cache import (
    read_cache,
    write_cache,
)


def write_output(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()

    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--our-forebet",
        type=Path,
        default=Path("data/forebet_current.csv"),
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--health-dir", type=Path)
    parser.add_argument(
        "--alias-cache",
        type=Path,
        default=Path("multibetter/data/forebet_bridge_aliases.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("multibetter/data/multibetter_current.csv"),
    )
    parser.add_argument(
        "--health-output",
        type=Path,
        default=Path("multibetter/data/multibetter_current_health.json"),
    )
    args = parser.parse_args()

    our_rows = read_csv_rows(args.our_forebet)
    sources = load_source_tables(
        args.source_dir,
        health_dir=args.health_dir,
    )
    cache = read_cache(args.alias_cache)

    result = build_current(
        our_forebet_rows=our_rows,
        source_tables=sources,
        cache_rows=cache,
    )

    write_output(args.output, list(result.rows))
    write_cache(args.alias_cache, list(result.alias_cache))

    args.health_output.parent.mkdir(parents=True, exist_ok=True)
    args.health_output.write_text(
        json.dumps(
            {
                "rows": len(result.rows),
                "learned_alias_count": result.learned_alias_count,
                "alias_cache_rows": len(result.alias_cache),
                "status_counts": dict(result.status_counts),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": len(result.rows),
                "learned_alias_count": result.learned_alias_count,
                "alias_cache_rows": len(result.alias_cache),
                "status_counts": dict(result.status_counts),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
