from __future__ import annotations

import csv
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reconcile_forebet_availability.py"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    spec = importlib.util.spec_from_file_location("reconcile_forebet_availability", SCRIPT)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load reconcile script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        current = root / "forebet_current.csv"
        availability = root / "forebet_availability.csv"
        targets = root / "hkjc_targets.csv"

        # Explicitly empty model feed: header only.
        write_csv(
            current,
            ["hkjc_event_id", "hkjc_home_team", "hkjc_away_team", "hkjc_kickoff_hkt"],
            [],
        )
        write_csv(
            targets,
            ["hkjc_event_id", "kickoff_hkt", "league_zh", "home_en", "away_en"],
            [
                {
                    "hkjc_event_id": "FBOUT1",
                    "kickoff_hkt": "2026-10-04 20:00",
                    "league_zh": "TEST",
                    "home_en": "Alpha",
                    "away_en": "Beta",
                },
                {
                    "hkjc_event_id": "FBOUT2",
                    "kickoff_hkt": "2026-10-04 21:00",
                    "league_zh": "TEST",
                    "home_en": "Gamma",
                    "away_en": "Delta",
                },
            ],
        )
        write_csv(
            availability,
            [
                "checked_at_hkt", "match_date", "kickoff_hkt", "hkjc_event_id",
                "league_zh", "home_en", "away_en", "state", "reason",
            ],
            [
                {
                    "checked_at_hkt": "2026-10-03T14:00:00+08:00",
                    "match_date": "2026-10-04",
                    "kickoff_hkt": "2026-10-04 20:00",
                    "hkjc_event_id": "FBOUT1",
                    "league_zh": "TEST",
                    "home_en": "Alpha",
                    "away_en": "Beta",
                    "state": "UNRESOLVED",
                    "reason": "forebet_source_surface_unavailable",
                }
            ],
        )

        module.CURRENT = current
        module.AVAILABILITY = availability
        module.TARGETS = targets

        rc = module.main()
        if rc != 0:
            raise SystemExit(f"unexpected reconcile return code {rc}")

        rows = read_csv(availability)
        by_id = {row["hkjc_event_id"]: row for row in rows}
        if set(by_id) != {"FBOUT1", "FBOUT2"}:
            raise SystemExit(f"availability universe mismatch: {sorted(by_id)}")
        if any(row["state"] == "MODEL" for row in rows):
            raise SystemExit("source outage fabricated a MODEL state")
        if by_id["FBOUT1"]["reason"] != "forebet_source_surface_unavailable":
            raise SystemExit("existing source-outage reason was overwritten")
        if by_id["FBOUT2"]["reason"] != "target_missing_from_forebet_scan_output":
            raise SystemExit("missing target was not materialized explicitly")

        print("PASS forebet_outage_reconcile feed=0 targets=2 availability=2 models=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
