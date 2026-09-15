from __future__ import annotations

import csv
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "forebet_current.csv"
TARGET_OUT = ROOT / "data" / "hkjc_targets.csv"
HKT = ZoneInfo("Asia/Hong_Kong")

FOOTYLOGIC_URL = "https://footylogic.com/en"
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "").strip()
SCRAPERAPI_URL = "https://api.scraperapi.com"
MAX_COST = "12"

LOOKBACK_MINUTES = 15
LOOKAHEAD_HOURS = 30
MAX_FOREBET_DATES = 2

COLUMNS = [
    "fetched_at_hkt", "match_date", "kickoff_text", "league_short",
    "home_team", "away_team", "prob_home", "prob_draw", "prob_away",
    "prediction_1x2", "predicted_score", "avg_goals", "odds_home",
    "odds_draw", "odds_away", "prediction_ou25", "prob_over25",
    "prob_under25", "odds_over25", "odds_under25",
    "hkjc_league", "hkjc_home_team", "hkjc_away_team",
    "hkjc_kickoff_hkt", "match_score",
]

TARGET_COLUMNS = [
    "match_date", "kickoff_hkt", "league", "home_team", "away_team"
]

TEAM_STOPWORDS = {
    "fc", "cf", "afc", "sc", "ac", "fk", "club", "de", "the"
}

ALIASES = {
    "tottenham hotspur": "tottenham",
    "tottenham": "tottenham",
    "west ham united": "west ham",
    "west ham": "west ham",
    "rayo vallecano": "vallecano",
    "cf elche": "elche",
    "elche cf": "elche",
    "pisa sc": "pisa",
    "pisa calcio": "pisa",
    "internazionale": "inter milan",
    "inter": "inter milan",
    "manchester united": "man united",
    "man utd": "man united",
    "manchester city": "man city",
    "sporting cp": "sporting",
    "athletic bilbao": "athletic club",
    "athletic club bilbao": "athletic club",
    "bayern munich": "bayern",
    "bayern munchen": "bayern",
    "paris saint germain": "psg",
}


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


def strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(ch)
    )


def normalize_team(value: str) -> str:
    value = strip_accents(value).casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if value in ALIASES:
        value = ALIASES[value]
    tokens = [t for t in value.split() if t not in TEAM_STOPWORDS]
    value = " ".join(tokens).strip()
    return ALIASES.get(value, value)


def team_score(a: str, b: str) -> float:
    a_n = normalize_team(a)
    b_n = normalize_team(b)
    if not a_n or not b_n:
        return 0.0
    if a_n == b_n:
        return 1.0
    if min(len(a_n), len(b_n)) >= 5 and (a_n in b_n or b_n in a_n):
        return 0.96

    seq = SequenceMatcher(None, a_n, b_n).ratio()
    a_tokens = set(a_n.split())
    b_tokens = set(b_n.split())
    if a_tokens and b_tokens:
        inter = len(a_tokens & b_tokens)
        token_score = 2 * inter / (len(a_tokens) + len(b_tokens))
    else:
        token_score = 0.0
    return max(seq, token_score)


def write_targets(targets: list[dict[str, Any]]) -> None:
    TARGET_OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = TARGET_OUT.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=TARGET_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in targets:
            writer.writerow({col: row.get(col, "") for col in TARGET_COLUMNS})
    tmp.replace(TARGET_OUT)


def load_hkjc_targets() -> list[dict[str, Any]]:
    now = datetime.now(HKT)
    start = now - timedelta(minutes=LOOKBACK_MINUTES)
    end = now + timedelta(hours=LOOKAHEAD_HOURS)

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=en-US")
    options.page_load_strategy = "eager"

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.execute_cdp_cmd(
            "Emulation.setTimezoneOverride",
            {"timezoneId": "Asia/Hong_Kong"},
        )
        driver.set_page_load_timeout(45)
        driver.get(FOOTYLOGIC_URL)

        WebDriverWait(driver, 35, poll_frequency=1).until(
            lambda d: " vs " in f" {d.find_element('tag name', 'body').text.lower()} "
        )
        time.sleep(2.0)
        html = driver.page_source
    except Exception as exc:
        print(f"FATAL: HKJC/Footylogic gate failed before Forebet request: {exc}", file=sys.stderr)
        return []
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    soup = BeautifulSoup(html, "lxml")
    current_date = None
    targets: list[dict[str, Any]] = []
    date_re = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    time_re = re.compile(r"^\d{1,2}:\d{2}$")

    for tr in soup.find_all("tr"):
        parts = [s.strip() for s in tr.stripped_strings if s.strip()]
        if not parts:
            continue

        header_date = next((p for p in parts if date_re.fullmatch(p)), None)
        if header_date:
            try:
                current_date = datetime.strptime(header_date, "%d/%m/%Y").date()
            except ValueError:
                current_date = None
            if "vs" not in [p.casefold() for p in parts]:
                continue

        lowered = [p.casefold() for p in parts]
        if "vs" not in lowered or current_date is None:
            continue

        try:
            vs_i = lowered.index("vs")
            home = parts[vs_i - 1].strip()
            away = parts[vs_i + 1].strip()
        except (ValueError, IndexError):
            continue
        if not home or not away:
            continue

        time_str = next((p for p in parts if time_re.fullmatch(p)), "")
        if not time_str:
            continue

        try:
            hh, mm = [int(x) for x in time_str.split(":", 1)]
            kickoff = datetime(
                current_date.year, current_date.month, current_date.day,
                hh, mm, tzinfo=HKT
            )
        except ValueError:
            continue

        if kickoff < start or kickoff > end:
            continue

        league = parts[0].strip() if parts else ""
        targets.append({
            "match_date": kickoff.date().isoformat(),
            "kickoff_hkt": kickoff.strftime("%Y-%m-%d %H:%M"),
            "league": league,
            "home_team": home,
            "away_team": away,
        })

    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in targets:
        key = (
            row["match_date"],
            normalize_team(row["home_team"]),
            normalize_team(row["away_team"]),
        )
        deduped[key] = row

    targets = sorted(
        deduped.values(),
        key=lambda r: (r["kickoff_hkt"], r["league"], r["home_team"]),
    )
    if not targets:
        print(
            "FATAL: HKJC/Footylogic returned zero target fixtures; "
            "ScraperAPI will not be called",
            file=sys.stderr,
        )
        return []

    write_targets(targets)
    dates = sorted({r["match_date"] for r in targets})
    print(
        f"HKJC_GATE targets={len(targets)} dates={','.join(dates)} "
        f"window_hours={LOOKAHEAD_HOURS}",
        flush=True,
    )
    for row in targets[:12]:
        print(
            f"  HKJC {row['kickoff_hkt']} | {row['league']} | "
            f"{row['home_team']} vs {row['away_team']}",
            flush=True,
        )
    if len(targets) > 12:
        print(f"  ... {len(targets) - 12} more HKJC targets", flush=True)
    return targets


def fetch_forebet_date(match_date: str) -> tuple[str | None, int | None]:
    if not SCRAPERAPI_KEY:
        print("FATAL: missing SCRAPERAPI_KEY GitHub Actions secret", file=sys.stderr)
        return None, None

    url = (
        "https://www.forebet.com/en/football-predictions/"
        f"predictions-1x2/{match_date}"
    )
    params = {
        "api_key": SCRAPERAPI_KEY,
        "url": url,
        "max_cost": MAX_COST,
    }
    try:
        r = requests.get(SCRAPERAPI_URL, params=params, timeout=70)
    except Exception as exc:
        print(
            f"ERROR: ScraperAPI request failed for {match_date}: {exc}",
            file=sys.stderr,
        )
        return None, None

    raw_cost = r.headers.get("sa-credit-cost")
    try:
        credit_cost = int(float(raw_cost)) if raw_cost else None
    except ValueError:
        credit_cost = None

    print(
        f"SCRAPERAPI date={match_date} status={r.status_code} "
        f"credit_cost={raw_cost or 'unknown'} bytes={len(r.text)}",
        flush=True,
    )
    if r.status_code != 200:
        print(
            f"ERROR: ScraperAPI non-200 for {match_date}; no retry",
            file=sys.stderr,
        )
        return None, credit_cost
    if "rcnt" not in r.text:
        print(
            f"ERROR: Forebet rows missing for {match_date}; no retry",
            file=sys.stderr,
        )
        return None, credit_cost
    return r.text, credit_cost


def parse_forebet_rows(html: str, requested_date: str) -> list[dict[str, Any]]:
    now = datetime.now(HKT)
    fetched_at = now.strftime("%Y-%m-%d %H:%M:%S")
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
        match_date = normalize_date(dt_attr, requested_date)

        prob_spans = row.select("div.fprc span")
        probs = [pct(text(sp)) for sp in prob_spans[:3]]
        while len(probs) < 3:
            probs.append(None)

        odds_spans = row.select("div.haodd span")
        odds = [decimal_odds(text(sp)) for sp in odds_spans[:3]]
        while len(odds) < 3:
            odds.append(None)

        prediction = (
            text(row.select_one("span.forepr span"))
            or text(row.select_one(".forepr"))
        )
        predicted_score = (
            text(row.select_one("div.ex_sc.tabonly"))
            or text(row.select_one(".predict_score, .ex_sc"))
        )
        avg_goals = (
            text(row.select_one("div.avg_sc.tabonly"))
            or text(row.select_one(".avg_sc"))
        )

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

    return rows


def attach_hkjc_target(
    row: dict[str, Any],
    targets: list[dict[str, Any]],
) -> dict[str, Any] | None:
    same_date = [t for t in targets if t["match_date"] == row["match_date"]]
    if not same_date:
        return None

    best = None
    best_avg = 0.0
    best_home = 0.0
    best_away = 0.0
    for target in same_date:
        hs = team_score(row["home_team"], target["home_team"])
        aws = team_score(row["away_team"], target["away_team"])
        avg = (hs + aws) / 2
        if avg > best_avg:
            best = target
            best_avg = avg
            best_home = hs
            best_away = aws

    if best is None:
        return None

    if best_home < 0.68 or best_away < 0.68 or best_avg < 0.76:
        return None

    out = dict(row)
    out.update({
        "hkjc_league": best["league"],
        "hkjc_home_team": best["home_team"],
        "hkjc_away_team": best["away_team"],
        "hkjc_kickoff_hkt": best["kickoff_hkt"],
        "match_score": round(best_avg, 3),
    })
    return out


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
    print("MODE=HKJC_GATE_THEN_FOREBET", flush=True)
    print(
        f"SCRAPERAPI_MAX_COST={MAX_COST} MAX_FOREBET_DATES={MAX_FOREBET_DATES}",
        flush=True,
    )

    targets = load_hkjc_targets()
    if not targets:
        return 2

    target_dates = sorted({r["match_date"] for r in targets})
    if len(target_dates) > MAX_FOREBET_DATES:
        print(
            f"WARN: target dates {target_dates}; limiting to first "
            f"{MAX_FOREBET_DATES} dates to protect credits",
            file=sys.stderr,
        )
        target_dates = target_dates[:MAX_FOREBET_DATES]

    parsed: list[dict[str, Any]] = []
    total_known_cost = 0
    calls = 0

    for match_date in target_dates:
        html, cost = fetch_forebet_date(match_date)
        calls += 1
        if cost is not None:
            total_known_cost += cost
        if html is None:
            continue
        parsed.extend(parse_forebet_rows(html, match_date))

    if not parsed:
        print(
            "FATAL: no Forebet rows retrieved for HKJC target dates; "
            "existing CSV preserved",
            file=sys.stderr,
        )
        return 2

    matched: list[dict[str, Any]] = []
    matched_target_keys: set[tuple[str, str, str]] = set()
    for row in parsed:
        selected = attach_hkjc_target(row, targets)
        if selected is None:
            continue
        matched.append(selected)
        matched_target_keys.add((
            selected["match_date"],
            normalize_team(selected["hkjc_home_team"]),
            normalize_team(selected["hkjc_away_team"]),
        ))

    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in matched:
        key = (
            row["match_date"],
            normalize_team(row["hkjc_home_team"]),
            normalize_team(row["hkjc_away_team"]),
        )
        old = unique.get(key)
        if old is None or float(row.get("match_score") or 0) > float(old.get("match_score") or 0):
            unique[key] = row
    matched = sorted(
        unique.values(),
        key=lambda r: (
            r.get("hkjc_kickoff_hkt", ""),
            r.get("hkjc_league", ""),
            r.get("hkjc_home_team", ""),
        ),
    )

    if not matched:
        print(
            "FATAL: Forebet returned data, but zero rows matched HKJC fixtures; "
            "existing CSV preserved",
            file=sys.stderr,
        )
        return 2

    good_probs = sum(
        1 for r in matched
        if all(
            isinstance(r.get(k), (int, float))
            for k in ("prob_home", "prob_draw", "prob_away")
        )
    )
    if good_probs == 0:
        print(
            "FATAL: matched HKJC rows contain no usable 1X2 probabilities; "
            "existing CSV preserved",
            file=sys.stderr,
        )
        return 2

    target_keys = {
        (
            r["match_date"],
            normalize_team(r["home_team"]),
            normalize_team(r["away_team"]),
        )
        for r in targets
        if r["match_date"] in target_dates
    }
    unmatched_count = len(target_keys - matched_target_keys)

    write_csv(matched)
    print(
        f"SUMMARY hkjc_targets={len(target_keys)} forebet_rows_seen={len(parsed)} "
        f"kept={len(matched)} probability_rows={good_probs} "
        f"unmatched_hkjc={unmatched_count} scraperapi_calls={calls} "
        f"known_credit_cost={total_known_cost}",
        flush=True,
    )
    print(f"WROTE {OUT} rows={len(matched)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
