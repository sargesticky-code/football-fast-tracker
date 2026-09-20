from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

from multibetter.aliasing.registry import AliasCandidate, add_candidate_observation


FIELDS = [
    "github_forebet_alias",
    "our_forebet_candidate",
    "first_seen",
    "last_seen",
    "observation_count",
    "best_similarity",
    "latest_similarity",
    "distinct_opponents",
    "event_ids",
    "status",
    "reason",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def parse_candidate(row: dict[str, str]) -> AliasCandidate:
    return AliasCandidate(
        alias=row["github_forebet_alias"],
        target=row["our_forebet_candidate"],
        first_seen=datetime.fromisoformat(row["first_seen"]),
        last_seen=datetime.fromisoformat(row["last_seen"]),
        observation_count=int(row.get("observation_count") or 0),
        best_similarity=float(row.get("best_similarity") or 0),
        latest_similarity=float(row.get("latest_similarity") or 0),
        opponents=frozenset(
            x for x in (row.get("distinct_opponents") or "").split("|") if x
        ),
        event_ids=frozenset(
            x for x in (row.get("event_ids") or "").split("|") if x
        ),
        status=row.get("status") or "CANDIDATE",
        reason=row.get("reason") or "",
    )


def candidate_to_row(row: AliasCandidate) -> dict[str, str]:
    return {
        "github_forebet_alias": row.alias,
        "our_forebet_candidate": row.target,
        "first_seen": row.first_seen.isoformat(),
        "last_seen": row.last_seen.isoformat(),
        "observation_count": str(row.observation_count),
        "best_similarity": f"{row.best_similarity:.3f}",
        "latest_similarity": f"{row.latest_similarity:.3f}",
        "distinct_opponents": "|".join(sorted(row.opponents)),
        "event_ids": "|".join(sorted(row.event_ids)),
        "status": row.status.value if hasattr(row.status, "value") else str(row.status),
        "reason": row.reason,
    }


def update_candidates(
    existing_rows: list[dict[str, str]],
    observations: list[dict[str, str]],
) -> list[dict[str, str]]:
    state: dict[tuple[str, str], AliasCandidate] = {}
    for row in existing_rows:
        candidate = parse_candidate(row)
        state[(candidate.alias, candidate.target)] = candidate

    for obs in observations:
        alias = (obs.get("github_forebet_alias") or "").strip()
        target = (obs.get("our_forebet_candidate") or "").strip()
        if not alias or not target:
            continue

        key = (alias, target)
        observed_at = datetime.fromisoformat(obs["observed_at"])
        state[key] = add_candidate_observation(
            state.get(key),
            alias=alias,
            target=target,
            observed_at=observed_at,
            similarity=float(obs.get("similarity") or 0),
            opponent=(obs.get("opponent") or "").strip() or None,
            event_id=(obs.get("event_id") or "").strip() or None,
        )

    return [
        candidate_to_row(state[key])
        for key in sorted(state, key=lambda k: (k[0].lower(), k[1].lower()))
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("multibetter/data/forebet_bridge_candidates.csv"),
    )
    args = parser.parse_args()

    existing = read_rows(args.candidates)
    observations = read_rows(args.observations)
    updated = update_candidates(existing, observations)

    args.candidates.parent.mkdir(parents=True, exist_ok=True)
    with args.candidates.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(updated)


if __name__ == "__main__":
    main()
