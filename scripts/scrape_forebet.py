from __future__ import annotations

import csv
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "forebet_current.csv"
HKT = ZoneInfo("Asia/Hong_Kong")
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "").strip()
SCRAPERAPI_URL = "https://api.scraperapi.com"
TARGET_URL = "https://www.forebet.com/en/football-tips-and-predictions-for-today"
MAX_COST = "12"

COLUMNS = [
    "fetched_at_hkt", "match_date", "kickoff_text", "league_short",
    "home_team", "away_team", "prob_home", "prob_draw", "prob_away",
    "prediction_1x2", "predicted_score", "avg_goals", "odds_home",
    "odds_draw", "odds_away", "prediction_ou25", "prob_over25",
    "prob_under25", "odds_over25", "odds_under25",
]


def text(el: Tag | None) -> str:
    return el.get_text(" ", strip=True) if el else ""


def pct(s: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", "."))
    if not m:
        return None
    try:
        v = float(m.group(0))
        return v if 0 <= v <= 100 else None
    except ValueError:
        return None


def decimal_odds(s: str) -> float | None:
    s = s.strip().lower()
    if not s or s in {"-", "no", "down", "n/a"}:
        return None
    try:
        if "/" in s:
            a, b = s.split("/", 1)
            return round(float(a) / float(b) + 1, 3)
        v = float(s.replace(",", "."))
        return round(v, 3) if 1.0 <= v <= 1000 else None
    except (ValueError, ZeroDivisionError):
        return None


def normalize_date(value: str, fallback: str) -> str:
    value = value.strip()
    if len(value) >= 10 and re.match(r"\d{4}-\d{2}-\d{2}", value[:10]):
        return value[:10]
    return fallback


def fetch_once() -> tuple[str | None, str | None]:
    if not SCRAPERAPI_KEY:
        print("FATAL: missing SCRAPERAPI_KEY GitHub Actions secret", file=sys.stderr)
        return None, None

    params = {
        "api_key": SCRAPERAPI_KEY,
        "url": TARGET_URL,
        "max_cost": MAX_COST,
    }
    try:
        r = requests.get(SCRAPERAPI_URL, params=params, timeout=70)
    except Exception as exc:
        print(f"FATAL: ScraperAPI request failed: {exc}", file=sys.stderr)
        return None, None

    credit_cost = r.headers.get("sa-credit-cost")
    print(
        f"SCRAPERAPI status={r.status_code} credit_cost={credit_cost or 'unknown'} "
        f"bytes={len(r.text)}",
        flush=True,
    )

    if r.status_code != 200:
        print("FATAL: ScraperAPI returned non-200; existing CSV preserved", file=sys.stderr)
        return None, credit_cost
    if "rcnt" not in r.text:
        print("FATAL: Forebet match rows not found; existing CSV preserved", file=sys.stderr)
        return None, credit_cost
    return r.text, credit_cost


def parse_rows(html: str) -> list[dict[str, Any]]:
    now = datetime.now(HKT)
    fetched_at = now.strftime("%Y-%m-%d %H:%M:%S")
    fallback_date = now.date().isoformat()
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict[str, Any]] = []

    for row in soup.select("div.rcnt"):
        home = text(row.select_one("span.homeTeam span[itemprop='name']"))
        away = text(row.select_one("span.awayTeam span[itemprop='name']"))
        if not home or not away:
            meta = row.find("meta", attrs={"itemprop": "name"})
            content = (meta.get("content") or "").strip() if meta else ""
            if " vs " in content:
                home, away = [x.strip() for x in content.split(" vs ", 1)]
        if not home or not away:
            continue

        time_el = row.find("time")
        dt_attr = str(time_el.get("datetime") or "") if time_el else ""
        match_date = normalize_date(dt_attr, fallback_date)

        prob_spans = row.select("div.fprc span")
        probs = [pct(text(sp)) for sp in prob_spans[:3]]
        while len(probs) < 3:
            probs.append(None)

        odds_spans = row.select("div.haodd span")
        odds = [decimal_odds(text(sp)) for sp in odds_spans[:3]]
        while len(odds) < 3:
            odds.append(None)

        prediction = text(row.select_one("span.forepr span")) or text(row.select_one(".forepr"))
        predicted_score = text(row.select_one("div.ex_sc.tabonly")) or text(row.select_one(".predict_score, .ex_sc"))
        avg_goals = text(row.select_one("div.avg_sc.tabonly")) or text(row.select_one(".avg_sc"))

        rows.append({
            "fetched_at_hkt": fetched_at,
            "match_date": match_date,
            "kickoff_text": text(row.select_one("span.date_bah")),
            "league_short": text(row.select_one("span.shortTag")),
            "home_team": home,
            "away_team": away,
            "prob_home": probs[0],
            "prob_draw": probs[1],
            "prob_away": probs[2],
            "prediction_1x2": prediction,
            "predicted_score": predicted_score,
            "avg_goals": avg_goals,
            "odds_home": odds[0],
            "odds_draw": odds[1],
            "odds_away": odds[2],
            "prediction_ou25": "",
            "prob_over25": "",
            "prob_under25": "",
            "odds_over25": "",
            "odds_under25": "",
        })

    rows.sort(key=lambda r: (
        r.get("match_date", ""), r.get("kickoff_text", ""),
        r.get("league_short", ""), r.get("home_team", "")
    ))
    return rows


def write_csv(rows: list[dict[str, Any]]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in COLUMNS})
    tmp.replace(OUT)


def main() -> int:
    print("FOREBET_MODE=ONE_REQUEST_DAILY_1X2", flush=True)
    print(f"SCRAPERAPI_MAX_COST={MAX_COST}", flush=True)
    html, credit_cost = fetch_once()
    if html is None:
        return 2

    rows = parse_rows(html)
    if not rows:
        print("FATAL: parsed zero Forebet rows; existing CSV preserved", file=sys.stderr)
        return 2

    good_probs = sum(
        1 for r in rows
        if all(isinstance(r.get(k), (int, float)) for k in ("prob_home", "prob_draw", "prob_away"))
    )
    print(
        f"SUMMARY rows={len(rows)} probability_rows={good_probs} "
        f"credit_cost={credit_cost or 'unknown'}",
        flush=True,
    )
    if good_probs == 0:
        print("FATAL: no usable 1X2 probability rows; existing CSV preserved", file=sys.stderr)
        return 2

    write_csv(rows)
    print(f"WROTE {OUT} rows={len(rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
