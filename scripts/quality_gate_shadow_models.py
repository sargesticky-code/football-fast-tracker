"""Fail closed on Dixon-Coles/Pi fits built from sparse HKJC target-team history.

HKJC target-team history is excellent for team-form models, but it is not a
complete league schedule. Dixon-Coles and Pi require a sufficiently connected
competition graph; fitting them to only the target teams plus one-off opponents
can produce degenerate probabilities. Keep football-data full-league fits, but
blank HKJC-network DC/Pi values and mark them explicitly as rejected.
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "model_current.csv"

MODEL_FIELDS = [
    "dc_prob_home", "dc_prob_draw", "dc_prob_away",
    "dc_xg_home", "dc_xg_away", "dc_prob_over25",
    "pi_prob_home", "pi_prob_draw", "pi_prob_away",
    "pi_home_rating", "pi_away_rating", "pi_diff", "training_matches",
]


def main() -> int:
    if not PATH.exists():
        raise SystemExit("missing data/model_current.csv")
    with PATH.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields:
        raise SystemExit("model_current.csv has no header")

    rejected = 0
    retained = 0
    for row in rows:
        source = str(row.get("model_source") or "")
        if source.startswith("HKJC matchResult"):
            for field in MODEL_FIELDS:
                if field in row:
                    row[field] = ""
            row["quality"] = "SPARSE_GRAPH_REJECTED"
            row["model_source"] = "HKJC history reserved for Team-Form Poisson"
            rejected += 1
        elif row.get("quality") == "MODELED":
            retained += 1

    tmp = PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(PATH)
    print(f"SHADOW_QUALITY_GATE retained_full_league={retained} rejected_sparse_hkjc={rejected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
