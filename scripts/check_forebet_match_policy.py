"""Regression checks for durable Forebet/HKJC team-name matching."""
from __future__ import annotations

import csv
from pathlib import Path

import scrape_forebet as feed
from forebet_match_policy import install, team_score

ROOT = Path(__file__).resolve().parent.parent

POSITIVE = [
    ("AIK Fotboll", "AIK Solna"),
    ("Mjällby AIF", "Mjallby"),
    ("FC Thun", "Thun"),
    ("Servette", "Servette"),
    ("Lugano", "Lugano"),
    ("St Gallen", "St. Gallen"),
    ("CA Progreso", "CA Progresso"),
    ("Nacional (URU)", "Montevideo Nacional"),
    ("Shorta Baghdad", "Al Shorta SC"),
    ("Al Seeb SC", "Al Seeb"),
    ("FC Nordsjælland", "Nordsjaelland"),
    ("Brøndby IF", "Brondby"),
    ("Malmö FF", "Malmo"),
    ("ŁKS Łódź", "LKS Lodz"),
]

NEGATIVE = [
    ("Real Madrid", "Real Sociedad"),
    ("Manchester City", "Leicester City"),
]


STATIC_ALIASES = {
    "León W": "Club Leon Women",
    "Juárez W": "Juarez Women",
    "Toluca W": "Toluca Women",
    "Tigres UANL W": "Tigres UANL Women",
    "Santos Laguna W": "Santos Laguna Women",
    "Cruz Azul W": "Cruz Azul Women",
}


def check_static_registry() -> None:
    # Install loads durable manual aliases into the legacy normalizer used by
    # the production matcher. These assertions prevent future clean-up from
    # silently removing recurring Liga MX Women identity mappings.
    install()
    for source_name, canonical in STATIC_ALIASES.items():
        left = feed.normalize_team(source_name)
        right = feed.normalize_team(canonical)
        if left != right:
            raise SystemExit(
                f"static alias regression: {source_name!r} -> {canonical!r} "
                f"normalized={left!r}/{right!r}"
            )
        print(f"STATIC_ALIAS {source_name} -> {canonical}")

    path = ROOT / "data" / "competition_alias_manual.csv"
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    routes = {
        (
            str(row.get("source") or "").strip().upper(),
            str(row.get("source_competition") or "").strip(),
            str(row.get("hkjc_tournament") or "").strip(),
        ): str(row.get("competition_url") or "").strip()
        for row in rows
        if str(row.get("status") or "").strip().upper() == "VERIFIED"
    }
    key = ("FOREBET", "MxW", "MXLW")
    if key not in routes or "liga-mx-women" not in routes[key]:
        raise SystemExit("missing durable Forebet MxW -> MXLW competition route")
    print(f"STATIC_COMPETITION {key[1]} -> {key[2]} {routes[key]}")


def main() -> int:
    check_static_registry()
    for forebet, hkjc in POSITIVE:
        score = team_score(forebet, hkjc)
        if score < 0.90:
            raise SystemExit(f"positive match failed: {forebet!r} -> {hkjc!r} score={score:.3f}")
        print(f"PASS {forebet} -> {hkjc} score={score:.3f}")
    for left, right in NEGATIVE:
        score = team_score(left, right)
        if score >= 0.90:
            raise SystemExit(f"negative guard failed: {left!r} vs {right!r} score={score:.3f}")
        print(f"GUARD {left} != {right} score={score:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
