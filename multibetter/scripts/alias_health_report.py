from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def conflicts(rows: list[dict[str, str]], alias_col: str, target_col: str):
    mapping: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        alias = (row.get(alias_col) or "").strip()
        target = (row.get(target_col) or "").strip()
        if alias:
            mapping[alias].add(target)
    return {
        alias: sorted(targets)
        for alias, targets in mapping.items()
        if len(targets) > 1
    }


def build_report(root: Path) -> dict:
    fast_registry = read_csv(root / "data/team_alias_registry.csv")
    fast_manual = read_csv(root / "data/team_alias_manual.csv")
    fast_unresolved = read_csv(root / "data/team_alias_unresolved.csv")

    bridge_verified = read_csv(
        root / "multibetter/data/forebet_bridge_aliases.csv"
    )
    bridge_candidates = read_csv(
        root / "multibetter/data/forebet_bridge_candidates.csv"
    )

    return {
        "fast_tracker": {
            "registry_rows": len(fast_registry),
            "manual_rows": len(fast_manual),
            "unresolved_rows": len(fast_unresolved),
            "registry_statuses": dict(
                Counter((r.get("status") or "UNKNOWN") for r in fast_registry)
            ),
            "registry_conflicts": conflicts(
                fast_registry,
                "forebet_alias",
                "canonical_hkjc_name",
            ),
            "manual_conflicts": conflicts(
                fast_manual,
                "forebet_alias",
                "canonical_hkjc_name",
            ),
        },
        "multibetter_bridge": {
            "verified_alias_rows": len(bridge_verified),
            "candidate_rows": len(bridge_candidates),
            "candidate_statuses": dict(
                Counter((r.get("status") or "UNKNOWN") for r in bridge_candidates)
            ),
            "verified_conflicts": conflicts(
                bridge_verified,
                "github_forebet_alias",
                "our_forebet_name",
            ),
            "candidate_conflicts": conflicts(
                bridge_candidates,
                "github_forebet_alias",
                "our_forebet_candidate",
            ),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_report(args.root)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
