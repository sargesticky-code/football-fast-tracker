from __future__ import annotations

import csv
import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "quality_gate_shadow_models.py"


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "hkjc_event_id","home","away","model_home_name","model_away_name",
        "dc_prob_home","dc_prob_draw","dc_prob_away","dc_xg_home","dc_xg_away",
        "dc_prob_over25","pi_prob_home","pi_prob_draw","pi_prob_away",
        "pi_home_rating","pi_away_rating","pi_diff","training_matches",
        "quality","model_source"
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    spec = importlib.util.spec_from_file_location("quality_gate_shadow_models", SCRIPT)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load quality gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "model_current.csv"
        base = {
            "dc_prob_home":"0.3","dc_prob_draw":"0.3","dc_prob_away":"0.4",
            "dc_xg_home":"1.1","dc_xg_away":"1.2","dc_prob_over25":"0.52",
            "pi_prob_home":"0.31","pi_prob_draw":"0.29","pi_prob_away":"0.40",
            "pi_home_rating":"1","pi_away_rating":"2","pi_diff":"-1",
            "training_matches":"311","quality":"MODELED",
            "model_source":"football-data.co.uk extra / penaltyblog 1.12.2",
        }
        write_rows(path, [
            {
                **base,
                "hkjc_event_id":"FBW",
                "home":"Spartak Moscow Women","away":"Zenit St. Petersburg Women",
                "model_home_name":"Spartak Moscow","model_away_name":"Zenit",
            },
            {
                **base,
                "hkjc_event_id":"FBM",
                "home":"Spartak Moscow","away":"Zenit St. Petersburg",
                "model_home_name":"Spartak Moscow","model_away_name":"Zenit St. Petersburg",
            },
        ])
        module.PATH = path
        if module.main() != 0:
            raise SystemExit("quality gate returned nonzero")
        rows = {r["hkjc_event_id"]: r for r in read_rows(path)}
        if rows["FBW"]["quality"] != "IDENTITY_VARIANT_REJECTED":
            raise SystemExit("women-to-men identity mismatch was not rejected")
        if any(rows["FBW"].get(k) for k in ("dc_prob_home","dc_xg_home","pi_prob_home","training_matches")):
            raise SystemExit("rejected identity retained model outputs")
        if rows["FBM"]["quality"] != "MODELED":
            raise SystemExit("valid same-variant identity was incorrectly rejected")
        print("PASS model_variant_identity rejected_cross_variant=1 retained_same_variant=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
