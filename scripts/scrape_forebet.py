from __future__ import annotations

import csv
import random
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import cloudscraper
import requests
from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "forebet_current.csv"
HKT = ZoneInfo("Asia/Hong_Kong")
DAYS_AHEAD = 7

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

COLUMNS = [
    "fetched_at_hkt", "match_date", "kickoff_text", "league_short",
    "home_team", "away_team", "prob_home", "prob_draw", "prob_away",
    "prediction_1x2", "predicted_score", "avg_goals", "odds_home",
    "odds_draw", "odds_away", "prediction_ou25", "prob_over25",
    "prob_under25", "odds_over25", "odds_under25",
]

MARKETS = {
    "1x2": "predictions-1x2",
    "ou25": "under-over-25-goals",
}

PLAIN = requests.Session()
PLAIN.headers.update(HEADERS)
CLOUD = cloudscraper.create_scraper()
CLOUD.headers.update(HEADERS)


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


def normalize_date(value: str) -> str:
    value = value.strip()
    if len(value) >= 10 and re.match(r"\d{4}-\d{2}-\d{2}", value[:10]):
        return value[:10]
    return ""


def highlighted_probability_index(spans: list[Tag]) -> int | None:
    for i, sp in enumerate(spans):
        classes = sp.get("class") or []
        if isinstance(classes, str):
            classes = classes.split()
        if "fpr" in classes:
            return i
    return None


def match_key(match_date: str, home: str, away: str) -> tuple[str, str, str]:
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", s.casefold())
    return match_date, norm(home), norm(away)


def looks_like_forebet(html: str) -> bool:
    low = html.casefold()
    return "rcnt" in html or ("forebet" in low and "football" in low and "<html" in low)


def fetch_html(url: str) -> str | None:
    # One normal HTTP request, then one cloudscraper HTTP fallback. No browser.
    for label, client in (("requests", PLAIN), ("cloudscraper", CLOUD)):
        try:
            r = client.get(url, timeout=18, allow_redirects=True)
            if r.status_code == 200 and looks_like_forebet(r.text):
                return r.text
            print(
                f"WARN {label} {url} status={r.status_code} "
                f"bytes={len(r.text)} rows_marker={'yes' if 'rcnt' in r.text else 'no'}",
                file=sys.stderr,
            )
        except Exception as exc:
            print(f"WARN {label} {url}: {exc}", file=sys.stderr)
    return None


def common_fields(row: Tag, requested_date: str) -> dict[str, Any] | None:
    home = text(row.select_one("span.homeTeam span[itemprop='name']"))
    away = text(row.select_one("span.awayTeam span[itemprop='name']"))
    if not home or not away:
        meta = row.find("meta", attrs={"itemprop": "name"})
        content = (meta.get("content") or "").strip() if meta else ""
        if " vs " in content:
            home, away = [x.strip() for x in content.split(" vs ", 1)]
    if not home or not away:
        return None

    time_el = row.find("time")
    match_date = normalize_date(str(time_el.get("datetime") or "")) if time_el else ""
    if match_date and match_date != requested_date:
        return None
    if not match_date:
        match_date = requested_date

    return {
        "match_date": match_date,
        "kickoff_text": text(row.select_one("span.date_bah")),
        "league_short": text(row.select_one("span.shortTag")),
        "home_team": home,
        "away_team": away,
    }


def parse_1x2_page(html: str, requested_date: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, Any]] = []
    for row in soup.select("div.rcnt"):
        base = common_fields(row, requested_date)
        if not base:
            continue
        prob_spans = row.select("div.fprc span")
        probs = [pct(text(sp)) for sp in prob_spans[:3]]
        while len(probs) < 3:
            probs.append(None)
        odds_spans = row.select("div.haodd span")
        odds = [decimal_odds(text(sp)) for sp in odds_spans[:3]]
        while len(odds) < 3:
            odds.append(None)
        pred = text(row.select_one("span.forepr span")) or text(row.select_one(".forepr"))
        score = text(row.select_one("div.ex_sc.tabonly")) or text(row.select_one(".predict_score, .ex_sc"))
        avg = text(row.select_one("div.avg_sc.tabonly")) or text(row.select_one(".avg_sc"))
        base.update({
            "prob_home": probs[0], "prob_draw": probs[1], "prob_away": probs[2],
            "prediction_1x2": pred, "predicted_score": score, "avg_goals": avg,
            "odds_home": odds[0], "odds_draw": odds[1], "odds_away": odds[2],
        })
        out.append(base)
    return out


def parse_ou_page(html: str, requested_date: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, Any]] = []
    for row in soup.select("div.rcnt"):
        base = common_fields(row, requested_date)
        if not base:
            continue
        pred = text(row.select_one("span.forepr span")) or text(row.select_one(".forepr"))
        prob_spans = row.select("div.fprc span")[:2]
        prob_vals = [pct(text(sp)) for sp in prob_spans]
        hi = highlighted_probability_index(prob_spans)
        prob_over = prob_under = None
        if len(prob_vals) >= 2 and hi in (0, 1):
            other = 1 - hi
            if pred.casefold().startswith("over"):
                prob_over, prob_under = prob_vals[hi], prob_vals[other]
            elif pred.casefold().startswith("under"):
                prob_under, prob_over = prob_vals[hi], prob_vals[other]
        if prob_over is None or prob_under is None:
            for sp, val in zip(prob_spans, prob_vals):
                classes = sp.get("class") or []
                cls = " ".join(classes if isinstance(classes, list) else [classes]).casefold()
                if "over" in cls:
                    prob_over = val
                elif "under" in cls:
                    prob_under = val
        odds_spans = row.select("div.haodd span")
        odds = [decimal_odds(text(sp)) for sp in odds_spans[:2]]
        while len(odds) < 2:
            odds.append(None)
        base.update({
            "prediction_ou25": pred,
            "prob_over25": prob_over, "prob_under25": prob_under,
            "odds_over25": odds[0], "odds_under25": odds[1],
        })
        out.append(base)
    return out


def scrape() -> tuple[list[dict[str, Any]], int, int]:
    now = datetime.now(HKT)
    fetched_at = now.strftime("%Y-%m-%d %H:%M:%S")
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    pages_ok = 0
    pages_failed = 0

    for offset in range(DAYS_AHEAD + 1):
        d = (now.date() + timedelta(days=offset)).isoformat()
        print(f"DATE {d}", flush=True)
        for market, slug in MARKETS.items():
            url = f"https://www.forebet.com/en/football-predictions/{slug}/{d}"
            html = fetch_html(url)
            if html is None:
                pages_failed += 1
                print(f"ERROR no HTML: {market} {d}", file=sys.stderr, flush=True)
                continue
            pages_ok += 1
            rows = parse_1x2_page(html, d) if market == "1x2" else parse_ou_page(html, d)
            print(f"  {market}: {len(rows)} rows", flush=True)
            for part in rows:
                key = match_key(part["match_date"], part["home_team"], part["away_team"])
                target = merged.setdefault(key, {})
                target.update({k: v for k, v in part.items() if v not in (None, "")})
                target.setdefault("fetched_at_hkt", fetched_at)
            time.sleep(random.uniform(0.25, 0.55))

    rows = list(merged.values())
    rows.sort(key=lambda r: (
        r.get("match_date", ""), r.get("kickoff_text", ""),
        r.get("league_short", ""), r.get("home_team", "")
    ))
    return rows, pages_ok, pages_failed


def existing_data_rows() -> int:
    if not OUT.exists():
        return 0
    try:
        with OUT.open(newline="", encoding="utf-8-sig") as fh:
            return max(sum(1 for _ in csv.reader(fh)) - 1, 0)
    except OSError:
        return 0


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
    rows, pages_ok, pages_failed = scrape()
    old_rows = existing_data_rows()
    print(
        f"SUMMARY rows={len(rows)} pages_ok={pages_ok} "
        f"pages_failed={pages_failed} old_rows={old_rows}", flush=True
    )
    if not rows:
        print("FATAL: zero current rows; preserving existing CSV", file=sys.stderr)
        return 2
    write_csv(rows)
    print(f"WROTE {OUT} rows={len(rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
