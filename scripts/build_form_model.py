"""Build a transparent global Team-Form Poisson shadow model from HKJC results.

Unlike Dixon-Coles/Pi, this model does not need a complete league schedule. It
uses each target team's own official HKJC result history, exact HKJC team ids,
recency weights and venue-specific scoring/conceding rates. It is shadow-only
and intentionally simple so it can cover leagues where free full-league history
is unavailable without pretending sparse data is a full competition graph.
"""
from __future__ import annotations

import csv
import io
import math
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from team_name_master import build_reverse_map

HKT = ZoneInfo("Asia/Hong_Kong")
ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "hkjc_history.csv"
TEAM_MAP = ROOT / "data" / "hkjc_current_teams.csv"
OUT = ROOT / "data" / "form_current.csv"

MIN_GAMES = 8
HALF_LIFE_DAYS = 180.0
MAX_GOALS = 10
WOMENS_RESULTS_URL = (
    "https://raw.githubusercontent.com/"
    "martj42/womens-international-results/master/results.csv"
)
WOMENS_RESULTS_TIMEOUT = 30

COLUMNS = [
    "fetched_at_hkt", "hkjc_event_id", "home", "away",
    "form_prob_home", "form_prob_draw", "form_prob_away",
    "form_xg_home", "form_xg_away", "home_games", "away_games",
    "home_venue_games", "away_venue_games", "quality", "model_source",
    "history_source", "external_home_games", "external_away_games",
    "external_latest_date",
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

def norm_name(value: str) -> str:
    value = "".join(
        ch for ch in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(ch)
    )
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def fallback_womens_source_name(hkjc_name: str) -> str:
    """Deterministic fallback only for senior AWF national-team names.

    Runtime mapping is master-first. These three country-name translations are
    kept only as a resilience fallback if the master endpoint is temporarily
    unavailable.
    """
    name = str(hkjc_name or "").strip()
    if not name.endswith(" Women") or any(tag in name for tag in (" U20", " U19", " U18", " U17")):
        return ""
    base = name[:-6].strip()
    return {
        "Korea Republic": "South Korea",
        "Korea DPR": "North Korea",
        "Chinese Taipei": "Taiwan",
    }.get(base, base)


def fetch_womens_international_results() -> tuple[list[dict], datetime | None]:
    try:
        response = requests.get(
            WOMENS_RESULTS_URL,
            timeout=WOMENS_RESULTS_TIMEOUT,
            headers={"User-Agent": "football-fast-tracker/1.0"},
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"WOMENS_INTL_HISTORY unavailable error={exc}", flush=True)
        return [], None

    rows: list[dict] = []
    latest: datetime | None = None
    try:
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            try:
                dt = datetime.strptime(str(row.get("date") or ""), "%Y-%m-%d").replace(tzinfo=HKT)
                hg = float(row.get("home_score") or "")
                ag = float(row.get("away_score") or "")
            except (TypeError, ValueError):
                continue
            item = {
                "date_dt": dt,
                "home": str(row.get("home_team") or "").strip(),
                "away": str(row.get("away_team") or "").strip(),
                "home_goals": hg,
                "away_goals": ag,
                "neutral": str(row.get("neutral") or "").strip().upper() == "TRUE",
            }
            if not item["home"] or not item["away"]:
                continue
            rows.append(item)
            if latest is None or dt > latest:
                latest = dt
    except Exception as exc:
        print(f"WOMENS_INTL_HISTORY parse_failed error={exc}", flush=True)
        return [], None

    print(
        f"WOMENS_INTL_HISTORY rows={len(rows)} "
        f"latest={latest.date().isoformat() if latest else '-'}",
        flush=True,
    )
    return rows, latest


def weighted_external_rate(
    rows: list[dict],
    team_name: str,
    kickoff: datetime,
    venue: str | None = None,
):
    total_w = gf = ga = 0.0
    n = 0
    for row in rows:
        home = str(row.get("home") or "")
        away = str(row.get("away") or "")
        if team_name not in (home, away):
            continue
        dt = row.get("date_dt")
        if not isinstance(dt, datetime) or dt >= kickoff:
            continue
        at_home = home == team_name
        neutral = bool(row.get("neutral"))
        if venue == "H" and (not at_home or neutral):
            continue
        if venue == "A" and (at_home or neutral):
            continue
        age_days = max(0.0, (kickoff - dt).total_seconds() / 86400.0)
        weight = math.exp(-math.log(2.0) * age_days / HALF_LIFE_DAYS)
        own = float(row["home_goals"] if at_home else row["away_goals"])
        opp = float(row["away_goals"] if at_home else row["home_goals"])
        total_w += weight
        gf += weight * own
        ga += weight * opp
        n += 1
    if n == 0 or total_w <= 0:
        return None
    return {"gf": gf / total_w, "ga": ga / total_w, "n": n, "weight": total_w}


def combine_rates(*rates):
    usable = [r for r in rates if r and r.get("weight", 0) > 0]
    if not usable:
        return None
    total_w = sum(float(r["weight"]) for r in usable)
    return {
        "gf": sum(float(r["gf"]) * float(r["weight"]) for r in usable) / total_w,
        "ga": sum(float(r["ga"]) * float(r["weight"]) for r in usable) / total_w,
        "n": sum(int(r["n"]) for r in usable),
        "weight": total_w,
    }



def weighted_rate(
    rows: list[dict],
    team_id: str,
    kickoff: datetime,
    venue: str | None = None,
    after: datetime | None = None,
):
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
        if after is not None and dt <= after:
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
    return {"gf": gf / total_w, "ga": ga / total_w, "n": n, "weight": total_w}


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
    women_rows, women_latest = fetch_womens_international_results()
    women_master = build_reverse_map("WOMENS_INTL_RESULTS", norm_name) if women_rows else {}
    women_cutoff = None
    if women_latest is not None:
        women_cutoff = women_latest.replace(hour=23, minute=59, second=59, microsecond=999999)

    now = datetime.now(HKT).replace(microsecond=0)
    out = []
    modeled = 0
    women_modeled = 0

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
        base["history_source"] = "HKJC"
        base["external_home_games"] = 0
        base["external_away_games"] = 0
        base["external_latest_date"] = ""

        # Senior women's internationals have a broad free historical result
        # source that is much denser than our incremental HKJC archive.
        # Universal team_name_master resolves HKJC names to dataset country names.
        if str(m.get("tournament") or "").strip() == "AWF" and women_rows:
            source_home = women_master.get(norm_name(str(m.get("home") or ""))) or fallback_womens_source_name(m.get("home", ""))
            source_away = women_master.get(norm_name(str(m.get("away") or ""))) or fallback_womens_source_name(m.get("away", ""))
            if source_home and source_away:
                h_ext = weighted_external_rate(women_rows, source_home, kickoff)
                a_ext = weighted_external_rate(women_rows, source_away, kickoff)
                h_ext_venue = weighted_external_rate(women_rows, source_home, kickoff, "H")
                a_ext_venue = weighted_external_rate(women_rows, source_away, kickoff, "A")

                # Avoid double-counting older matches already present in both
                # sources: combine the external archive with only HKJC results
                # after the external dataset's latest published date.
                h_recent = weighted_rate(history, home_id, kickoff, after=women_cutoff) if women_cutoff else None
                a_recent = weighted_rate(history, away_id, kickoff, after=women_cutoff) if women_cutoff else None
                h_recent_venue = weighted_rate(history, home_id, kickoff, "H", after=women_cutoff) if women_cutoff else None
                a_recent_venue = weighted_rate(history, away_id, kickoff, "A", after=women_cutoff) if women_cutoff else None

                h_all = combine_rates(h_ext, h_recent)
                a_all = combine_rates(a_ext, a_recent)
                h_venue = combine_rates(h_ext_venue, h_recent_venue)
                a_venue = combine_rates(a_ext_venue, a_recent_venue)
                base["history_source"] = "WOMENS_INTL_RESULTS+HKJC_RECENT"
                base["external_home_games"] = h_ext["n"] if h_ext else 0
                base["external_away_games"] = a_ext["n"] if a_ext else 0
                base["external_latest_date"] = women_latest.date().isoformat() if women_latest else ""
                base["model_source"] = (
                    "martj42/womens-international-results + HKJC recent · "
                    "recency-weighted Team-Form Poisson"
                )

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
        if base.get("history_source") == "WOMENS_INTL_RESULTS+HKJC_RECENT":
            women_modeled += 1
        out.append(base)

    out.sort(key=lambda r: r.get("hkjc_event_id", ""))
    write(out)
    print(
        f"FORM_MODEL fixtures={len(mappings)} modeled={modeled} "
        f"women_external_modeled={women_modeled} fail_closed={len(mappings)-modeled} "
        f"history_rows={len(history)} womens_history_rows={len(women_rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
