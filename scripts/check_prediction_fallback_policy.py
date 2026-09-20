"""Regression checks for APWin fallback fixture-link matching."""
from __future__ import annotations

from update_prediction_fallback import slug_scores

GOOD = [
    (
        "Ansan Greeners",
        "Chungbuk Cheongju",
        "https://www.apwin.com/predictions/ansan-greeners-vs-cheongju-prediction-k-league-2-20-09-2026/",
    ),
    (
        "Horsens",
        "AGF Aarhus",
        "https://www.apwin.com/predictions/horsens-vs-agf-prediction-superliga-20-09-2026/",
    ),
    (
        "Criciuma",
        "Operario Ferroviario",
        "https://www.apwin.com/predictions/criciuma-vs-operario-prediction-serie-b-21-09-2026/",
    ),
]

BAD = [
    (
        "Fiorentina",
        "Napoli",
        "https://www.apwin.com/predictions/lecce-u20-vs-fiorentina-u20-prediction-campionato-primavera-1-19-09-2026/",
    ),
    (
        "Getafe",
        "Malaga",
        "https://www.apwin.com/predictions/getafe-b-vs-talavera-cf-prediction-segunda-division-rfef-group-5-20-09-2026/",
    ),
    (
        "Montevideo Liverpool",
        "Racing Club Montevideo",
        "https://www.apwin.com/predictions/central-espanol-vs-montevideo-city-torque-prediction-primera-division-21-09-2026/",
    ),
]


def accepted(home: str, away: str, url: str) -> bool:
    hs, aws, avg = slug_scores(home, away, url)
    return avg >= 0.70 and min(hs, aws) >= 0.50


def main() -> int:
    for home, away, url in GOOD:
        hs, aws, avg = slug_scores(home, away, url)
        if not accepted(home, away, url):
            raise SystemExit(
                f"good APWin link rejected: {home} vs {away} hs={hs:.2f} aws={aws:.2f} avg={avg:.2f}"
            )
        print(f"PASS {home} vs {away} hs={hs:.2f} aws={aws:.2f} avg={avg:.2f}")

    for home, away, url in BAD:
        hs, aws, avg = slug_scores(home, away, url)
        if accepted(home, away, url):
            raise SystemExit(
                f"bad APWin link accepted: {home} vs {away} hs={hs:.2f} aws={aws:.2f} avg={avg:.2f}"
            )
        print(f"GUARD {home} vs {away} hs={hs:.2f} aws={aws:.2f} avg={avg:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
