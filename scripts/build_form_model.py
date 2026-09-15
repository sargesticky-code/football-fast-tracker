"""Build a transparent global Team-Form Poisson shadow model from HKJC results.

Unlike Dixon-Coles/Pi, this model does not need a complete league schedule. It
uses each target team's own official HKJC result history, exact HKJC team ids,
recency weights and venue-specific scoring/conceding rates. It is shadow-only
and intentionally simple so it can cover leagues where free full-league history
is unavailable without pretending sparse data is a full competition graph.
"""
from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")
ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "hkjc_history.csv"
TEAM_MAP = ROOT / "data" / "hkjc_current_teams.csv"
OUT = ROOT / "data" / "form_current.csv"

MIN_GAMES = 8
HALF_LIFE_DAYS = 180.0
MAX_GOALS = 10

COLUMNS = [
    "fetched_at_hkt", "hkjc_event_id", "home", "away",
    "form_prob_home", "form_prob_draw", "form_prob_away",
    "form_xg_home", "form_xg_away", "home_games", "away_games",
    "home_venue_games", "away_venue_games", "quality", "model_source",
]


def read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def parse_dt(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HKT)
    return dt.astimezone(HKT)


def weighted_rate(rows: list[dict], team_id: str, kickoff: datetime, venue: str | None = None):
    total_w = gf = ga = 0.0
    n = 0
    for r in rows:
        home_id = str(r.get("home_id") or "")
        away_id = str(r.get("away_id") or "")
        if team_id not in (home_id, away_id):
            continue
        at_home = home_id == team_id
        if venue == "H" and not at_home:
            continue
        if venue == "A" and at_home:
            continue
        dt = parse_dt(r.get("kickoff_hkt", ""))
        if dt is None or dt >= kickoff:
            continue
        try:
            hg = float(r.get("home_goals", ""))
            ag = float(r.get("away_goals", ""))
        except (TypeError, ValueError):
            continue
        age_days = max(0.0, (kickoff - dt).total_seconds() / 86400.0)
        w = math.exp(-math.log(2.0) * age_days / HALF_LIFE_DAYS)
        own, opp = (hg, ag) if at_home else (ag, hg)
        total_w += w
        gf += w * own
        ga += w * opp
        n += 1
    if n == 0 or total_w <= 0:
        return None
    return {"gf": gf / total_w, "ga": ga / total_w, "n": n}


def blend(all_rate, venue_rate):
    if all_rate is None:
        return None
    if venue_rate is None or venue_rate["n"] < 4:
        return all_rate
    # Venue split is useful but noisier; shrink it toward the all-match rate.
    venue_weight = min(0.70, 0.40 + 0.03 * venue_rate["n"])
    all_weight = 1.0 - venue_weight
    return {
        "gf": venue_weight * venue_rate["gf"] + all_weight * all_rate["gf"],
        "ga": venue_weight * venue_rate["ga"] + all_weight * all_rate["ga"],
        "n": all_rate["n"],
    }


def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def probabilities(lh: float, la: float):
    home = draw = away = 0.0
    for h in range(MAX_GOALS + 1):
        ph = poisson_pmf(h, lh)
        for a in range(MAX_GOALS + 1):
            p = ph * poisson_pmf(a, la)
            if h > a:
                home += p
            elif h == a:
                draw += p
            else:
                away += p
    s = home + draw + away
    if s <= 0:
        return None
    return home / s, draw / s, away / s


def expected_goals(home_rate, away_rate):
    # Combine one side's scoring rate with the opponent's conceding rate.
    # Geometric mean dampens extreme samples more than a simple average.
    lh = math.sqrt(max(0.10, home_rate["gf"]) * max(0.10, away_rate["ga"]))
    la = math.sqrt(max(0.10, away_rate["gf"]) * max(0.10, home_rate["ga"]))
    # Fail-safe clipping only prevents numerical/extreme small-sample blowups;
    # it is not a hidden calibration to betting prices.
    return min(3.50, max(0.25, lh)), min(3.50, max(0.25, la))


def write(rows: list[dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in COLUMNS})
    tmp.replace(OUT)


def main() -> int:
    history = read(HISTORY)
    mappings = read(TEAM_MAP)
    now = datetime.now(HKT).replace(microsecond=0)
    out = []
    modeled = 0

    for m in mappings:
        event_id = m.get("hkjc_event_id", "")
        home_id = str(m.get("home_id") or "")
        away_id = str(m.get("away_id") or "")
        kickoff = parse_dt(m.get("kickoff_hkt", ""))
        base = {
            "fetched_at_hkt": now.isoformat(),
            "hkjc_event_id": event_id,
            "home": m.get("home", ""),
            "away": m.get("away", ""),
            "quality": "FORM_INSUFFICIENT",
            "model_source": "HKJC matchResult · recency-weighted Team-Form Poisson",
        }
        if not event_id or not home_id or not away_id or kickoff is None:
            out.append(base)
            continue

        h_all = weighted_rate(history, home_id, kickoff)
        a_all = weighted_rate(history, away_id, kickoff)
        h_venue = weighted_rate(history, home_id, kickoff, "H")
        a_venue = weighted_rate(history, away_id, kickoff, "A")
        base["home_games"] = h_all["n"] if h_all else 0
        base["away_games"] = a_all["n"] if a_all else 0
        base["home_venue_games"] = h_venue["n"] if h_venue else 0
        base["away_venue_games"] = a_venue["n"] if a_venue else 0

        if not h_all or not a_all or h_all["n"] < MIN_GAMES or a_all["n"] < MIN_GAMES:
            base["quality"] = f"FORM_INSUFFICIENT:{base['home_games']}/{base['away_games']}"
            out.append(base)
            continue

        h_rate = blend(h_all, h_venue)
        a_rate = blend(a_all, a_venue)
        lh, la = expected_goals(h_rate, a_rate)
        probs = probabilities(lh, la)
        if probs is None or not all(math.isfinite(x) for x in probs):
            base["quality"] = "FORM_FAIL"
            out.append(base)
            continue

        base.update({
            "form_prob_home": f"{probs[0]:.6f}",
            "form_prob_draw": f"{probs[1]:.6f}",
            "form_prob_away": f"{probs[2]:.6f}",
            "form_xg_home": f"{lh:.5f}",
            "form_xg_away": f"{la:.5f}",
            "quality": "FORM_MODELED",
        })
        modeled += 1
        out.append(base)

    out.sort(key=lambda r: r.get("hkjc_event_id", ""))
    write(out)
    print(f"FORM_MODEL fixtures={len(mappings)} modeled={modeled} fail_closed={len(mappings)-modeled} history_rows={len(history)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
