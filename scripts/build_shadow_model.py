"""Build an independent Dixon-Coles + Pi shadow feed for current Fast Tracker games.

The model deliberately does NOT use Forebet probabilities, HKJC prices, Bet365
prices or Opta ratings as training features.  It trains from football-data.co.uk
results, so it can be compared honestly against the external models/markets.

Coverage is fail-closed: if a fixture cannot be matched confidently to a league
with adequate free history, the row is retained with quality=UNSUPPORTED_HISTORY
and blank model probabilities instead of inventing a prediction.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import penaltyblog as pb
import requests

HKT = ZoneInfo("Asia/Hong_Kong")
ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "forebet_current.csv"
OUT = ROOT / "data" / "model_current.csv"
BASE = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
TIMEOUT = 30

LEAGUES = {
    "E0": "ENG Premier League",
    "E1": "ENG Championship",
    "SP1": "ESP La Liga",
    "D1": "GER Bundesliga",
    "I1": "ITA Serie A",
    "F1": "FRA Ligue 1",
    "N1": "NED Eredivisie",
    "P1": "POR Primeira Liga",
    "SC0": "SCO Premiership",
    "B1": "BEL First Division A",
    "T1": "TUR Super Lig",
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
    "bayern munich": "bayern munich",
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
    codes = []
    for s in (start, start - 1, start - 2):
        codes.append(f"{s % 100:02d}{(s + 1) % 100:02d}")
    return codes


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


def best_name(name: str, candidates: set[str]) -> tuple[str | None, float]:
    if not candidates:
        return None, 0.0
    scored = sorted(((sim(name, c), c) for c in candidates), reverse=True)
    score, candidate = scored[0]
    # Avoid accepting a fuzzy tie as an authoritative alias.
    if len(scored) > 1 and score < 0.94 and score - scored[1][0] < 0.05:
        return None, score
    return (candidate, score) if score >= 0.78 else (None, score)


def discover_fixture(row: dict[str, str], current: dict[str, pd.DataFrame]):
    source_home = row.get("hkjc_home_team") or row.get("home_team") or ""
    source_away = row.get("hkjc_away_team") or row.get("away_team") or ""
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
    return df.reset_index(drop=True)


def fit_one(hist: pd.DataFrame, home: str, away: str) -> dict:
    if len(hist) < 120:
        raise ValueError(f"insufficient history {len(hist)}")
    team_games = pd.concat([
        hist.loc[(hist["HomeTeam"] == home) | (hist["AwayTeam"] == home)],
        hist.loc[(hist["HomeTeam"] == away) | (hist["AwayTeam"] == away)],
    ]).drop_duplicates()
    if len(team_games) < 20:
        raise ValueError("insufficient target-team history")

    weights = pb.models.dixon_coles_weights(hist["date_dt"], xi=0.001)
    model = pb.models.DixonColesGoalModel(
        hist["FTHG"].astype(int),
        hist["FTAG"].astype(int),
        hist["HomeTeam"].astype(str),
        hist["AwayTeam"].astype(str),
        weights=weights,
    )
    model.fit()
    pred = model.predict(home, away, max_goals=10)
    ph, pd_, pa = [float(x) for x in pred.home_draw_away]

    pi = pb.ratings.PiRatingSystem()
    for r in hist.itertuples(index=False):
        pi.update_ratings(str(r.HomeTeam), str(r.AwayTeam), int(r.FTHG) - int(r.FTAG))
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


def fmt_prob(value) -> str:
    return "" if value in (None, "") else f"{float(value):.6f}"


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
        raise SystemExit("missing data/forebet_current.csv")
    with FEED.open(encoding="utf-8-sig", newline="") as fh:
        fixtures = list(csv.DictReader(fh))
    if not fixtures:
        write([])
        print("SHADOW_MODEL fixtures=0")
        return 0

    now = datetime.now(HKT)
    seasons = season_codes(now)
    session = requests.Session()

    # Cheap discovery: current-season table only for each supported league.
    current: dict[str, pd.DataFrame] = {code: fetch_csv(session, seasons[0], code) for code in LEAGUES}
    discovered = {r["hkjc_event_id"]: discover_fixture(r, current) for r in fixtures}
    needed_codes = sorted({d[1] for d in discovered.values() if d})

    histories: dict[str, pd.DataFrame] = {}
    for code in needed_codes:
        parts = [current.get(code, pd.DataFrame())]
        for season in seasons[1:]:
            parts.append(fetch_csv(session, season, code))
        histories[code] = clean_history(parts)

    fetched = now.replace(microsecond=0).isoformat()
    out: list[dict] = []
    modeled = 0
    for fixture in fixtures:
        event_id = fixture.get("hkjc_event_id", "")
        source_home = fixture.get("hkjc_home_team") or fixture.get("home_team") or ""
        source_away = fixture.get("hkjc_away_team") or fixture.get("away_team") or ""
        base = {
            "fetched_at_hkt": fetched,
            "hkjc_event_id": event_id,
            "home": source_home,
            "away": source_away,
            "quality": "UNSUPPORTED_HISTORY",
            "model_source": "penaltyblog 1.12.2 / football-data.co.uk",
        }
        found = discovered.get(event_id)
        if not found:
            out.append(base)
            continue
        quality, code, home, away, hs, aws = found
        base.update({
            "model_league": LEAGUES[code],
            "model_home_name": home,
            "model_away_name": away,
            "team_match_quality": f"{quality:.3f}",
        })
        try:
            values = fit_one(histories[code], home, away)
            for k, v in list(values.items()):
                if k.startswith("dc_prob") or k.startswith("pi_prob"):
                    values[k] = fmt_prob(v)
                elif isinstance(v, float):
                    values[k] = f"{v:.5f}"
            base.update(values)
            base["quality"] = "MODELED"
            modeled += 1
        except Exception as exc:
            base["quality"] = f"MODEL_FAIL:{type(exc).__name__}"
        out.append(base)

    out.sort(key=lambda r: r.get("hkjc_event_id", ""))
    write(out)
    print(
        f"SHADOW_MODEL fixtures={len(fixtures)} modeled={modeled} "
        f"unsupported={len(fixtures)-modeled} leagues={','.join(needed_codes) or '-'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
