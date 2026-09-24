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
EXTERNAL_LOOKBACK_DAYS = 730
MIN_EFFECTIVE_WEIGHT = 3.0
MIN_VENUE_EFFECTIVE_WEIGHT = 1.5
MAX_GOALS = 10
WOMENS_RESULTS_URL = (
    "https://raw.githubusercontent.com/"
    "martj42/womens-international-results/master/results.csv"
)
WOMENS_RESULTS_TIMEOUT = 30
MENS_RESULTS_URL = (
    "https://raw.githubusercontent.com/"
    "martj42/international_results/master/results.csv"
)
MENS_RESULTS_TIMEOUT = 20
# HKJC tournament codes currently used for senior men's national-team fixtures.
# Name checks below additionally exclude youth, AM and women's fixtures.
SENIOR_MENS_TOURNAMENTS = frozenset({
    "INT",  # senior internationals / friendlies
    "ANQ",  # Africa senior qualification
    "GUC",  # Gulf senior competition
    "ENL",  # UEFA Nations League
    "CNL",  # CONCACAF Nations League
    "AEC",  # AFC senior competition
})
BRAZIL_RESULTS_URLS = (
    "https://raw.githubusercontent.com/BrazilianFootball/Data/main/results/processed/Serie_B_2025_games.json",
    "https://raw.githubusercontent.com/BrazilianFootball/Data/main/results/processed/Serie_C_2025_games.json",
)
BRAZIL_RESULTS_TIMEOUT = 40

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



def fetch_mens_international_results() -> tuple[list[dict], datetime | None]:
    try:
        response = requests.get(
            MENS_RESULTS_URL,
            timeout=MENS_RESULTS_TIMEOUT,
            headers={"User-Agent": "football-fast-tracker/1.0"},
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"MENS_INTL_HISTORY unavailable error={exc}", flush=True)
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
        print(f"MENS_INTL_HISTORY parse_failed error={exc}", flush=True)
        return [], None

    print(
        f"MENS_INTL_HISTORY rows={len(rows)} "
        f"latest={latest.date().isoformat() if latest else '-'}",
        flush=True,
    )
    return rows, latest


def external_team_name_index(rows: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows:
        for key in ("home", "away"):
            name = str(row.get(key) or "").strip()
            norm = norm_name(name)
            if norm and norm not in out:
                out[norm] = name
    return out

def clean_brazil_team(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r"\s*/\s*[A-Z]{2}\s*$", "", value)
    value = re.sub(r"\s+-\s*$", "", value)
    return value.strip()


def fetch_brazilianfootball_results() -> tuple[list[dict], datetime | None]:
    rows: list[dict] = []
    latest: datetime | None = None
    for url in BRAZIL_RESULTS_URLS:
        try:
            response = requests.get(
                url,
                timeout=BRAZIL_RESULTS_TIMEOUT,
                headers={"User-Agent": "football-fast-tracker/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            print(f"BRAZIL_HISTORY unavailable url={url} error={exc}", flush=True)
            continue

        games = payload.values() if isinstance(payload, dict) else []
        source_rows = 0
        for game in games:
            if not isinstance(game, dict):
                continue
            try:
                dt = datetime.strptime(str(game.get("Date") or ""), "%d/%m/%Y").replace(tzinfo=HKT)
                m = re.search(r"(\d+)\s*[Xx]\s*(\d+)", str(game.get("Result") or ""))
                if not m:
                    continue
                hg = float(m.group(1))
                ag = float(m.group(2))
            except (TypeError, ValueError):
                continue
            home = clean_brazil_team(game.get("Home", ""))
            away = clean_brazil_team(game.get("Away", ""))
            if not home or not away:
                continue
            rows.append({
                "date_dt": dt,
                "home": home,
                "away": away,
                "home_goals": hg,
                "away_goals": ag,
                "neutral": False,
            })
            source_rows += 1
            if latest is None or dt > latest:
                latest = dt
        print(
            f"BRAZIL_HISTORY_SOURCE url={url.rsplit('/',1)[-1]} rows={source_rows}",
            flush=True,
        )

    # Same match cannot occur in both Serie B and C in one season, but keep a
    # deterministic de-duplication guard in case the source later changes.
    dedup: dict[tuple[str,str,str],dict] = {}
    for row in rows:
        key=(row["date_dt"].date().isoformat(),norm_name(row["home"]),norm_name(row["away"]))
        dedup[key]=row
    rows=list(dedup.values())
    print(
        f"BRAZIL_HISTORY rows={len(rows)} "
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
        if age_days > EXTERNAL_LOOKBACK_DAYS:
            continue
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
    if (
        venue_rate is None
        or venue_rate["n"] < 4
        or float(venue_rate.get("weight", 0.0)) < MIN_VENUE_EFFECTIVE_WEIGHT
    ):
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

    mens_rows, mens_latest = fetch_mens_international_results()
    mens_names = external_team_name_index(mens_rows)
    mens_cutoff = None
    if mens_latest is not None:
        mens_cutoff = mens_latest.replace(hour=23, minute=59, second=59, microsecond=999999)

    brazil_rows, brazil_latest = fetch_brazilianfootball_results()
    brazil_master = build_reverse_map("BRAZILIANFOOTBALL_DATA", norm_name) if brazil_rows else {}
    brazil_cutoff = None
    if brazil_latest is not None:
        brazil_cutoff = brazil_latest.replace(hour=23, minute=59, second=59, microsecond=999999)

    now = datetime.now(HKT).replace(microsecond=0)
    out = []
    modeled = 0
    women_modeled = 0
    mens_modeled = 0
    brazil_modeled = 0

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

        # Senior men's internationals: use the broad full-international archive,
        # but only for known senior national-team tournament codes. Youth / AM
        # fixtures are deliberately excluded and remain fail-closed.
        tournament = str(m.get("tournament") or "").strip()
        home_name = str(m.get("home") or "").strip()
        away_name = str(m.get("away") or "").strip()
        youth_markers = (" U21", " U23", " U20", " U19", " U18", " U17", " AM", " Women")
        senior_men = (
            tournament in SENIOR_MENS_TOURNAMENTS
            and not any(marker in home_name or marker in away_name for marker in youth_markers)
        )
        if senior_men and mens_rows:
            source_home = mens_names.get(norm_name(home_name))
            source_away = mens_names.get(norm_name(away_name))
            if source_home and source_away:
                h_ext = weighted_external_rate(mens_rows, source_home, kickoff)
                a_ext = weighted_external_rate(mens_rows, source_away, kickoff)
                h_ext_venue = weighted_external_rate(mens_rows, source_home, kickoff, "H")
                a_ext_venue = weighted_external_rate(mens_rows, source_away, kickoff, "A")

                h_recent = weighted_rate(history, home_id, kickoff, after=mens_cutoff) if mens_cutoff else None
                a_recent = weighted_rate(history, away_id, kickoff, after=mens_cutoff) if mens_cutoff else None
                h_recent_venue = weighted_rate(history, home_id, kickoff, "H", after=mens_cutoff) if mens_cutoff else None
                a_recent_venue = weighted_rate(history, away_id, kickoff, "A", after=mens_cutoff) if mens_cutoff else None

                h_all = combine_rates(h_ext, h_recent)
                a_all = combine_rates(a_ext, a_recent)
                h_venue = combine_rates(h_ext_venue, h_recent_venue)
                a_venue = combine_rates(a_ext_venue, a_recent_venue)
                base["history_source"] = "MENS_INTL_RESULTS+HKJC_RECENT"
                base["external_home_games"] = h_ext["n"] if h_ext else 0
                base["external_away_games"] = a_ext["n"] if a_ext else 0
                base["external_latest_date"] = mens_latest.date().isoformat() if mens_latest else ""
                base["model_source"] = (
                    "martj42/international_results + HKJC recent · "
                    "recency-weighted Team-Form Poisson"
                )

        # Brazil Serie B current targets: use the public BrazilianFootball/Data
        # 2025 Serie B/C result archive as the long-run base, then append only
        # HKJC results newer than that archive. This fills promoted/relegated
        # teams without mixing divisions into a single league-strength graph.
        if str(m.get("tournament") or "").strip() == "BD2" and brazil_rows:
            source_home = brazil_master.get(norm_name(str(m.get("home") or "")))
            source_away = brazil_master.get(norm_name(str(m.get("away") or "")))
            if source_home and source_away:
                h_ext = weighted_external_rate(brazil_rows, source_home, kickoff)
                a_ext = weighted_external_rate(brazil_rows, source_away, kickoff)
                h_ext_venue = weighted_external_rate(brazil_rows, source_home, kickoff, "H")
                a_ext_venue = weighted_external_rate(brazil_rows, source_away, kickoff, "A")

                h_recent = weighted_rate(history, home_id, kickoff, after=brazil_cutoff) if brazil_cutoff else None
                a_recent = weighted_rate(history, away_id, kickoff, after=brazil_cutoff) if brazil_cutoff else None
                h_recent_venue = weighted_rate(history, home_id, kickoff, "H", after=brazil_cutoff) if brazil_cutoff else None
                a_recent_venue = weighted_rate(history, away_id, kickoff, "A", after=brazil_cutoff) if brazil_cutoff else None

                h_all = combine_rates(h_ext, h_recent)
                a_all = combine_rates(a_ext, a_recent)
                h_venue = combine_rates(h_ext_venue, h_recent_venue)
                a_venue = combine_rates(a_ext_venue, a_recent_venue)
                base["history_source"] = "BRAZILIANFOOTBALL_SERIE_BC_2025+HKJC_RECENT"
                base["external_home_games"] = h_ext["n"] if h_ext else 0
                base["external_away_games"] = a_ext["n"] if a_ext else 0
                base["external_latest_date"] = brazil_latest.date().isoformat() if brazil_latest else ""
                base["model_source"] = (
                    "BrazilianFootball/Data Serie B-C 2025 + HKJC recent · "
                    "recency-weighted Team-Form Poisson"
                )

        base["home_games"] = h_all["n"] if h_all else 0
        base["away_games"] = a_all["n"] if a_all else 0
        base["home_venue_games"] = h_venue["n"] if h_venue else 0
        base["away_venue_games"] = a_venue["n"] if a_venue else 0

        if (
            not h_all
            or not a_all
            or h_all["n"] < MIN_GAMES
            or a_all["n"] < MIN_GAMES
            or float(h_all.get("weight", 0.0)) < MIN_EFFECTIVE_WEIGHT
            or float(a_all.get("weight", 0.0)) < MIN_EFFECTIVE_WEIGHT
        ):
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
        if base.get("history_source") == "MENS_INTL_RESULTS+HKJC_RECENT":
            mens_modeled += 1
        if base.get("history_source") == "BRAZILIANFOOTBALL_SERIE_BC_2025+HKJC_RECENT":
            brazil_modeled += 1
        out.append(base)

    out.sort(key=lambda r: r.get("hkjc_event_id", ""))
    write(out)
    print(
        f"FORM_MODEL fixtures={len(mappings)} modeled={modeled} "
        f"women_external_modeled={women_modeled} mens_external_modeled={mens_modeled} "
        f"brazil_external_modeled={brazil_modeled} "
        f"fail_closed={len(mappings)-modeled} history_rows={len(history)} "
        f"womens_history_rows={len(women_rows)} mens_history_rows={len(mens_rows)} "
        f"brazil_history_rows={len(brazil_rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
