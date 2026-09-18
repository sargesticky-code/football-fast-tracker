"""Build independent Dixon-Coles + Pi shadow probabilities for Fast Tracker.

Priority order:
1) football-data.co.uk league history for well-covered European leagues.
2) HKJC's own matchResult history (stable team ids) as a global fallback.

No Forebet probabilities, HKJC prices, Bet365 prices or Opta ratings are used as
training features. Coverage is fail-closed: unsupported fixtures stay in the
output with blank probabilities rather than receiving invented numbers.
"""
from __future__ import annotations

import csv
import io
import os
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pandas as pd
import penaltyblog as pb
import requests

HKT = ZoneInfo("Asia/Hong_Kong")
ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "hkjc_current.csv"
OUT = ROOT / "data" / "model_current.csv"
HKJC_HISTORY = ROOT / "data" / "hkjc_history.csv"
HKJC_TEAMS = ROOT / "data" / "hkjc_current_teams.csv"
BASE = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
TIMEOUT = 30
MODEL_LOOKBACK_DAYS = int(os.getenv("MODEL_LOOKBACK_DAYS", "540"))
MODEL_MAX_MATCHES = int(os.getenv("MODEL_MAX_MATCHES", "700"))

LEAGUES = {
    "E0": "ENG Premier League",
    "E1": "ENG Championship",
    "E2": "ENG League One",
    "E3": "ENG League Two",
    "EC": "ENG National League",
    "SC0": "SCO Premiership",
    "SC1": "SCO Championship",
    "SC2": "SCO League One",
    "SC3": "SCO League Two",
    "D1": "GER Bundesliga",
    "D2": "GER Bundesliga 2",
    "I1": "ITA Serie A",
    "I2": "ITA Serie B",
    "SP1": "ESP La Liga",
    "SP2": "ESP Segunda",
    "F1": "FRA Ligue 1",
    "F2": "FRA Ligue 2",
    "N1": "NED Eredivisie",
    "B1": "BEL First Division A",
    "P1": "POR Primeira Liga",
    "T1": "TUR Super Lig",
    "G1": "GRE Super League",
}

# Football-Data's newer country files provide long-run top-flight history for
# additional leagues.  We discover the current CSV link from the country page
# instead of hard-coding the file token, so a site-side filename change does
# not silently break the model.
EXTRA_COUNTRY_PAGES = {
    "Argentina": "https://www.football-data.co.uk/argentina.php",
    "Austria": "https://www.football-data.co.uk/austria.php",
    "Brazil": "https://www.football-data.co.uk/brazil.php",
    "China": "https://www.football-data.co.uk/china.php",
    "Denmark": "https://www.football-data.co.uk/denmark.php",
    "Finland": "https://www.football-data.co.uk/finland.php",
    "Ireland": "https://www.football-data.co.uk/ireland.php",
    "Japan": "https://www.football-data.co.uk/japan.php",
    "Mexico": "https://www.football-data.co.uk/mexico.php",
    "Norway": "https://www.football-data.co.uk/norway.php",
    "Poland": "https://www.football-data.co.uk/poland.php",
    "Romania": "https://www.football-data.co.uk/romania.php",
    "Russia": "https://www.football-data.co.uk/russia.php",
    "Sweden": "https://www.football-data.co.uk/sweden.php",
    "Switzerland": "https://www.football-data.co.uk/switzerland.php",
    "USA": "https://www.football-data.co.uk/usa.php",
}

COLUMNS = [
    "fetched_at_hkt", "hkjc_event_id", "home", "away", "model_league",
    "model_home_name", "model_away_name", "dc_prob_home", "dc_prob_draw",
    "dc_prob_away", "dc_xg_home", "dc_xg_away", "dc_prob_over25",
    "pi_prob_home", "pi_prob_draw", "pi_prob_away", "pi_home_rating",
    "pi_away_rating", "pi_diff", "training_matches", "team_match_quality",
    "quality", "model_source",
]

ALIASES = {
    "man utd": "manchester united",
    "manchester utd": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham",
    "tottenham hotspur": "tottenham",
    "wolves": "wolverhampton wanderers",
    "wolverhampton": "wolverhampton wanderers",
    "newcastle": "newcastle united",
    "west ham": "west ham united",
    "brighton": "brighton and hove albion",
    "athletic bilbao": "athletic club",
    "atletico de madrid": "atletico madrid",
    "real betis": "betis",
    "inter milan": "inter",
    "internazionale": "inter",
    "paris saint germain": "paris sg",
    "psg": "paris sg",
    "bayern munchen": "bayern munich",
    "borussia dortmund": "dortmund",
    "sporting lisbon": "sporting cp",
}


def norm(value: str) -> str:
    value = "".join(c for c in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(c))
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    for suffix in (" football club", " futebol clube", " fc", " cf", " afc"):
        if value.endswith(suffix):
            value = value[: -len(suffix)].strip()
    return ALIASES.get(value, value)


def sim(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if min(len(a), len(b)) >= 5 and (a in b or b in a):
        return 0.94
    return SequenceMatcher(None, a, b).ratio()


def season_codes(now: datetime) -> list[str]:
    y = now.year
    start = y if now.month >= 7 else y - 1
    return [f"{s % 100:02d}{(s + 1) % 100:02d}" for s in (start, start - 1, start - 2)]


def fetch_csv(session: requests.Session, season: str, code: str) -> pd.DataFrame:
    url = BASE.format(season=season, code=code)
    r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": "football-fast-tracker/1.0"})
    if r.status_code != 200 or len(r.content) < 100:
        return pd.DataFrame()
    try:
        df = pd.read_csv(io.BytesIO(r.content))
    except Exception:
        return pd.DataFrame()
    required = {"HomeTeam", "AwayTeam", "FTHG", "FTAG", "Date"}
    if not required.issubset(df.columns):
        return pd.DataFrame()
    return df



def standardize_result_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize old and new Football-Data schemas to the model's five fields."""
    if df.empty:
        return pd.DataFrame()
    choices = {
        "HomeTeam": ("HomeTeam", "Home"),
        "AwayTeam": ("AwayTeam", "Away"),
        "FTHG": ("FTHG", "HG"),
        "FTAG": ("FTAG", "AG"),
        "Date": ("Date",),
    }
    picked: dict[str, str] = {}
    for target, candidates in choices.items():
        source = next((x for x in candidates if x in df.columns), None)
        if source is None:
            return pd.DataFrame()
        picked[target] = source
    out = pd.DataFrame({target: df[source] for target, source in picked.items()})
    return out


def fetch_extra_country(session: requests.Session, page_url: str) -> pd.DataFrame:
    """Resolve and fetch one Football-Data extra-league historical CSV."""
    try:
        page = session.get(
            page_url,
            timeout=TIMEOUT,
            headers={"User-Agent": "football-fast-tracker/1.0"},
        )
        page.raise_for_status()
        hrefs = re.findall(r"""href=["']([^"']+\.csv)["']""", page.text, flags=re.I)
        candidates = [urljoin(page_url, h) for h in hrefs if "/new/" in urljoin(page_url, h)]
        if not candidates:
            return pd.DataFrame()
        # Country pages expose one canonical CSV link. Prefer the shortest URL
        # if the page happens to include more than one CSV reference.
        csv_url = sorted(set(candidates), key=len)[0]
        r = session.get(
            csv_url,
            timeout=TIMEOUT,
            headers={"User-Agent": "football-fast-tracker/1.0"},
        )
        r.raise_for_status()
        df = pd.read_csv(io.BytesIO(r.content))
        return standardize_result_frame(df)
    except Exception:
        return pd.DataFrame()


def best_name(name: str, candidates: set[str]) -> tuple[str | None, float]:
    if not candidates:
        return None, 0.0
    scored = sorted(((sim(name, c), c) for c in candidates), reverse=True)
    score, candidate = scored[0]
    if len(scored) > 1 and score < 0.94 and score - scored[1][0] < 0.05:
        return None, score
    return (candidate, score) if score >= 0.78 else (None, score)


def discover_fixture(row: dict[str, str], current: dict[str, pd.DataFrame]):
    source_home = row.get("hkjc_home_team") or row.get("home_en") or row.get("home_team") or ""
    source_away = row.get("hkjc_away_team") or row.get("away_en") or row.get("away_team") or ""
    best = None
    for code, df in current.items():
        if df.empty:
            continue
        teams = set(df["HomeTeam"].dropna().astype(str)) | set(df["AwayTeam"].dropna().astype(str))
        home, hs = best_name(source_home, teams)
        away, aws = best_name(source_away, teams)
        if not home or not away or home == away:
            continue
        quality = (hs + aws) / 2
        if best is None or quality > best[0]:
            best = (quality, code, home, away, hs, aws)
    if best is None or best[0] < 0.82:
        return None
    return best


def clean_history(parts: list[pd.DataFrame]) -> pd.DataFrame:
    good = [p.copy() for p in parts if not p.empty]
    if not good:
        return pd.DataFrame()
    df = pd.concat(good, ignore_index=True)
    df = df.dropna(subset=["HomeTeam", "AwayTeam", "FTHG", "FTAG", "Date"])
    df["FTHG"] = pd.to_numeric(df["FTHG"], errors="coerce")
    df["FTAG"] = pd.to_numeric(df["FTAG"], errors="coerce")
    df["date_dt"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["FTHG", "FTAG", "date_dt"])
    df = df.sort_values("date_dt").drop_duplicates(subset=["date_dt", "HomeTeam", "AwayTeam"], keep="last")

    # Production models are intentionally recent. Old seasons are useful for
    # archival research but should not dominate current tactical/player reality.
    cutoff = pd.Timestamp.now(tz=None) - pd.Timedelta(days=MODEL_LOOKBACK_DAYS)
    recent = df.loc[df["date_dt"] >= cutoff].copy()
    if not recent.empty:
        df = recent
    if MODEL_MAX_MATCHES > 0 and len(df) > MODEL_MAX_MATCHES:
        df = df.tail(MODEL_MAX_MATCHES)
    return df.reset_index(drop=True)


def fit_one(
    hist: pd.DataFrame,
    home: str,
    away: str,
    *,
    min_matches: int = 120,
    min_team_games: int = 20,
    fit_cache: dict[str, tuple] | None = None,
    cache_key: str | None = None,
) -> dict:
    if len(hist) < min_matches:
        raise ValueError(f"insufficient history {len(hist)}")
    home_games = hist.loc[(hist["HomeTeam"] == home) | (hist["AwayTeam"] == home)]
    away_games = hist.loc[(hist["HomeTeam"] == away) | (hist["AwayTeam"] == away)]
    if len(home_games) < min_team_games or len(away_games) < min_team_games:
        raise ValueError(f"insufficient target-team history {len(home_games)}/{len(away_games)}")

    cached = fit_cache.get(cache_key) if fit_cache is not None and cache_key else None
    if cached is None:
        weights = pb.models.dixon_coles_weights(hist["date_dt"], xi=0.001)
        model = pb.models.DixonColesGoalModel(
            hist["FTHG"].astype(int),
            hist["FTAG"].astype(int),
            hist["HomeTeam"].astype(str),
            hist["AwayTeam"].astype(str),
            weights=weights,
        )
        model.fit()

        pi = pb.ratings.PiRatingSystem()
        for r in hist.sort_values("date_dt").itertuples(index=False):
            pi.update_ratings(str(r.HomeTeam), str(r.AwayTeam), int(r.FTHG) - int(r.FTAG))
        if fit_cache is not None and cache_key:
            fit_cache[cache_key] = (model, pi)
    else:
        model, pi = cached

    pred = model.predict(home, away, max_goals=10)
    ph, pd_, pa = [float(x) for x in pred.home_draw_away]
    pp = pi.calculate_match_probabilities(home, away)
    home_rating = float(pi.get_team_rating(home))
    away_rating = float(pi.get_team_rating(away))

    return {
        "dc_prob_home": ph,
        "dc_prob_draw": pd_,
        "dc_prob_away": pa,
        "dc_xg_home": float(pred.home_goal_expectation),
        "dc_xg_away": float(pred.away_goal_expectation),
        "dc_prob_over25": float(pred.total_goals("over", 2.5)),
        "pi_prob_home": float(pp["home_win"]),
        "pi_prob_draw": float(pp["draw"]),
        "pi_prob_away": float(pp["away_win"]),
        "pi_home_rating": home_rating,
        "pi_away_rating": away_rating,
        "pi_diff": home_rating - away_rating,
        "training_matches": len(hist),
    }


def load_hkjc_inputs() -> tuple[pd.DataFrame, dict[str, dict[str, str]]]:
    if not HKJC_HISTORY.exists() or not HKJC_TEAMS.exists():
        return pd.DataFrame(), {}
    try:
        h = pd.read_csv(HKJC_HISTORY, dtype=str)
        with HKJC_TEAMS.open(encoding="utf-8-sig", newline="") as fh:
            maps = {r["hkjc_event_id"]: r for r in csv.DictReader(fh) if r.get("hkjc_event_id")}
    except Exception:
        return pd.DataFrame(), {}
    required = {"match_id", "kickoff_hkt", "tournament", "home_id", "away_id", "home_goals", "away_goals"}
    if h.empty or not required.issubset(h.columns):
        return pd.DataFrame(), maps
    h["FTHG"] = pd.to_numeric(h["home_goals"], errors="coerce")
    h["FTAG"] = pd.to_numeric(h["away_goals"], errors="coerce")
    h["date_dt"] = pd.to_datetime(h["kickoff_hkt"], errors="coerce", utc=True).dt.tz_convert(None)
    h["HomeTeam"] = h["home_id"].fillna("").astype(str)
    h["AwayTeam"] = h["away_id"].fillna("").astype(str)
    h = h.dropna(subset=["FTHG", "FTAG", "date_dt"])
    h = h[(h["HomeTeam"] != "") & (h["AwayTeam"] != "")]
    h = h.sort_values("date_dt").drop_duplicates(subset=["match_id"], keep="last")
    return h.reset_index(drop=True), maps


def team_game_count(hist: pd.DataFrame, team_id: str) -> int:
    return int(((hist["HomeTeam"] == team_id) | (hist["AwayTeam"] == team_id)).sum())


def select_hkjc_history(all_hist: pd.DataFrame, mapping: dict[str, str]) -> tuple[pd.DataFrame, str]:
    if all_hist.empty:
        return pd.DataFrame(), ""
    home = str(mapping.get("home_id") or "")
    away = str(mapping.get("away_id") or "")
    tournament = str(mapping.get("tournament") or "")
    if not home or not away:
        return pd.DataFrame(), ""

    same = all_hist.loc[all_hist["tournament"].fillna("").astype(str) == tournament].copy()
    if len(same) >= 50 and team_game_count(same, home) >= 10 and team_game_count(same, away) >= 10:
        return same, f"HKJC {tournament}"

    selected_idx: set[int] = set()
    frontier = {home, away}
    known = set(frontier)
    for _ in range(3):
        mask = all_hist["HomeTeam"].isin(frontier) | all_hist["AwayTeam"].isin(frontier)
        idx = set(all_hist.index[mask].tolist())
        new_idx = idx - selected_idx
        if not new_idx:
            break
        selected_idx |= idx
        rows = all_hist.loc[sorted(new_idx)]
        discovered = set(rows["HomeTeam"].astype(str)) | set(rows["AwayTeam"].astype(str))
        frontier = discovered - known
        known |= discovered
        if len(selected_idx) >= 450:
            break
    if not selected_idx:
        return pd.DataFrame(), ""
    selected = all_hist.loc[sorted(selected_idx)].copy()
    if len(selected) > 500:
        selected = selected.sort_values("date_dt").tail(500)
    return selected, f"HKJC connected history ({tournament or 'mixed'})"


def fmt_prob(value) -> str:
    return "" if value in (None, "") else f"{float(value):.6f}"


def finalize_values(values: dict) -> dict:
    out = dict(values)
    for k, v in list(out.items()):
        if k.startswith("dc_prob") or k.startswith("pi_prob"):
            out[k] = fmt_prob(v)
        elif isinstance(v, float):
            out[k] = f"{v:.5f}"
    return out


def write(rows: list[dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in COLUMNS})
    tmp.replace(OUT)


def main() -> int:
    if not FEED.exists():
        raise SystemExit("missing data/hkjc_current.csv")
    with FEED.open(encoding="utf-8-sig", newline="") as fh:
        raw_fixtures = list(csv.DictReader(fh))
    fixtures = [
        r for r in raw_fixtures
        if str(r.get("hkjc_event_id") or "").strip()
        and str(r.get("selling") or "").strip() in ("1", "true", "TRUE")
        and all(str(r.get(k) or "").strip() for k in ("had_home", "had_draw", "had_away"))
    ]
    if not fixtures:
        write([])
        print("SHADOW_MODEL fixtures=0")
        return 0

    now = datetime.now(HKT)
    seasons = season_codes(now)
    session = requests.Session()

    current: dict[str, pd.DataFrame] = {}
    dataset_labels: dict[str, str] = {}

    # Main European divisions: discover against the current season, then train
    # on the current plus two preceding seasons.
    for code, label in LEAGUES.items():
        key = f"MAIN:{code}"
        frame = fetch_csv(session, seasons[0], code)
        current[key] = frame
        dataset_labels[key] = label

    # Extra leagues: each country file contains long-run top-flight history.
    # The same frame can therefore be used both for team discovery and fitting.
    for country, page_url in EXTRA_COUNTRY_PAGES.items():
        key = f"EXTRA:{country}"
        frame = fetch_extra_country(session, page_url)
        current[key] = frame
        dataset_labels[key] = f"{country} top flight"

    discovered = {r["hkjc_event_id"]: discover_fixture(r, current) for r in fixtures}
    needed_keys = sorted({d[1] for d in discovered.values() if d})
    histories: dict[str, pd.DataFrame] = {}
    for key in needed_keys:
        if key.startswith("MAIN:"):
            code = key.split(":", 1)[1]
            parts = [current.get(key, pd.DataFrame())]
            for season in seasons[1:]:
                parts.append(fetch_csv(session, season, code))
            histories[key] = clean_history(parts)
        else:
            histories[key] = clean_history([current.get(key, pd.DataFrame())])

    hkjc_hist, hkjc_maps = load_hkjc_inputs()

    fetched = now.replace(microsecond=0).isoformat()
    out: list[dict] = []
    football_data_fit_cache: dict[str, tuple] = {}
    modeled = 0
    modeled_fd = 0
    modeled_hkjc = 0

    for fixture in fixtures:
        event_id = fixture.get("hkjc_event_id", "")
        source_home = fixture.get("hkjc_home_team") or fixture.get("home_en") or fixture.get("home_team") or ""
        source_away = fixture.get("hkjc_away_team") or fixture.get("away_en") or fixture.get("away_team") or ""
        base = {
            "fetched_at_hkt": fetched,
            "hkjc_event_id": event_id,
            "home": source_home,
            "away": source_away,
            "quality": "UNSUPPORTED_HISTORY",
            "model_source": "none",
        }

        fd_error = None
        found = discovered.get(event_id)
        if found:
            quality, dataset_key, home, away, _hs, _aws = found
            base.update({
                "model_league": dataset_labels.get(dataset_key, dataset_key),
                "model_home_name": home,
                "model_away_name": away,
                "team_match_quality": f"{quality:.3f}",
            })
            try:
                values = fit_one(
                    histories[dataset_key],
                    home,
                    away,
                    min_matches=120,
                    min_team_games=20,
                    fit_cache=football_data_fit_cache,
                    cache_key=dataset_key,
                )
                base.update(finalize_values(values))
                base["quality"] = "MODELED"
                base["model_source"] = (
                    "football-data.co.uk extra / penaltyblog 1.12.2"
                    if dataset_key.startswith("EXTRA:")
                    else "football-data.co.uk main / penaltyblog 1.12.2"
                )
                modeled += 1
                modeled_fd += 1
                out.append(base)
                continue
            except Exception as exc:
                fd_error = f"{type(exc).__name__}:{exc}"

        mapping = hkjc_maps.get(event_id)
        if mapping:
            hist, label = select_hkjc_history(hkjc_hist, mapping)
            home_id = str(mapping.get("home_id") or "")
            away_id = str(mapping.get("away_id") or "")
            base.update({
                "model_league": label or f"HKJC {mapping.get('tournament','')}",
                "model_home_name": mapping.get("home") or source_home,
                "model_away_name": mapping.get("away") or source_away,
                "team_match_quality": "1.000",
            })
            try:
                values = fit_one(hist, home_id, away_id, min_matches=45, min_team_games=10)
                base.update(finalize_values(values))
                base["quality"] = "MODELED"
                base["model_source"] = "HKJC matchResult / penaltyblog 1.12.2"
                modeled += 1
                modeled_hkjc += 1
                out.append(base)
                continue
            except Exception as exc:
                base["quality"] = f"MODEL_FAIL:{type(exc).__name__}"
                base["model_source"] = "HKJC matchResult / penaltyblog 1.12.2"
        elif fd_error:
            base["quality"] = "MODEL_FAIL:FOOTBALL_DATA"
            base["model_source"] = "football-data.co.uk / penaltyblog 1.12.2"

        out.append(base)

    out.sort(key=lambda r: r.get("hkjc_event_id", ""))
    write(out)
    print(
        f"SHADOW_MODEL fixtures={len(fixtures)} modeled={modeled} "
        f"football_data={modeled_fd} hkjc_history={modeled_hkjc} "
        f"fail_closed={len(fixtures)-modeled} fd_datasets={','.join(needed_keys) or '-'} "
        f"hkjc_history_rows={len(hkjc_hist)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
