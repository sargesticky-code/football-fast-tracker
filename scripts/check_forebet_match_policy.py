"""Regression checks for durable Forebet/HKJC team-name matching."""
from __future__ import annotations

from forebet_match_policy import team_score

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


def main() -> int:
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
