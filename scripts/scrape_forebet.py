from __future__ import annotations

import csv
import io
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag

from team_name_master import build_forward_map

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "forebet_current.csv"
TARGET_OUT = ROOT / "data" / "hkjc_targets.csv"
HKT = ZoneInfo("Asia/Hong_Kong")

MASTER_SHEET_ID = "1WTyWLisEn_9-VmIqHK6TWZ4YGPbiejbBDfEpwv2BVRo"
HKJC_SNAPSHOT_GID = "910835842"
ACTIVE_ALIAS_GID = "432162540"
BILINGUAL_MAP_GID = "1745665072"

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "").strip()
SCRAPERAPI_URL = "https://api.scraperapi.com"
MAX_COST = "12"
GATE_ONLY = os.getenv("HKJC_GATE_ONLY", "0").strip() == "1"

LOOKBACK_MINUTES = 15
LOOKAHEAD_HOURS = 30
MAX_FOREBET_DATES = 2
MAX_SNAPSHOT_AGE_MINUTES = 120
HTTP_TIMEOUT = 45

COLUMNS = [
    "fetched_at_hkt", "match_date", "kickoff_text", "league_short",
    "home_team", "away_team", "prob_home", "prob_draw", "prob_away",
    "prediction_1x2", "predicted_score", "avg_goals", "odds_home",
    "odds_draw", "odds_away", "prediction_ou25", "prob_over25",
    "prob_under25", "odds_over25", "odds_under25", "forebet_detail_url",
    "hkjc_event_id", "hkjc_league", "hkjc_home_team", "hkjc_away_team",
    "hkjc_home_zh", "hkjc_away_zh", "hkjc_kickoff_hkt",
    "hkjc_had_home", "hkjc_had_draw", "hkjc_had_away", "match_score",
]

TARGET_COLUMNS = [
    "match_date", "kickoff_hkt", "hkjc_event_id", "league_zh",
    "home_zh", "away_zh", "home_en", "away_en",
    "had_home", "had_draw", "had_away", "mapping_source",
]

TEAM_STOPWORDS = {"fc", "cf", "afc", "sc", "ac", "fk", "club", "de", "the"}

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
    "heart of midlothian": "hearts",
    "heart of midlothian fc": "hearts",
    "jeonbuk hyundai motors": "jeonbuk motors",
    "jeonbuk hyundai": "jeonbuk motors",
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; FootballFastTracker/1.0)",
    "Accept": "text/csv,text/plain,*/*;q=0.8",
})

_FOREBET_MASTER: dict[str, str] | None = None


def forebet_master_map() -> dict[str, str]:
    """Load the verified universal dictionary once per production process."""
    global _FOREBET_MASTER
    if _FOREBET_MASTER is None:
        _FOREBET_MASTER = build_forward_map("FOREBET", normalize_team)
    return _FOREBET_MASTER


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


def normalize_zh(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().casefold()
    value = re.sub(r"[\s·・._\-—–'’\"()（）\[\]【】/]+", "", value)
    return value


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


def public_csv_url(gid: str) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{MASTER_SHEET_ID}/"
        f"export?format=csv&gid={gid}"
    )


def fetch_csv(gid: str, label: str) -> list[dict[str, str]]:
    url = public_csv_url(gid)
    try:
        r = SESSION.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
    except Exception as exc:
        print(f"FATAL: {label} CSV request failed: {exc}", file=sys.stderr)
        return []
    if r.status_code != 200:
        print(
            f"FATAL: {label} CSV status={r.status_code} bytes={len(r.content)}",
            file=sys.stderr,
        )
        return []
    try:
        decoded = r.content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        print(f"FATAL: {label} CSV UTF-8 decode failed: {exc}", file=sys.stderr)
        return []
    if "<html" in decoded[:500].casefold():
        print(f"FATAL: {label} returned HTML instead of CSV", file=sys.stderr)
        return []
    rows = list(csv.DictReader(io.StringIO(decoded)))
    print(f"HKJC_SOURCE {label} rows={len(rows)} bytes={len(r.content)}", flush=True)
    return rows


def parse_iso_utc(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def build_alias_maps(
    bilingual_rows: list[dict[str, str]],
    active_rows: list[dict[str, str]],
) -> tuple[dict[str, tuple[str, str, str]], dict[str, str]]:
    event_map: dict[str, tuple[str, str, str]] = {}
    zh_to_en: dict[str, str] = {}

    for row in bilingual_rows:
        event_id = (row.get("HKJC Event ID") or "").strip()
        home_en = (row.get("Home EN") or "").strip()
        away_en = (row.get("Away EN") or "").strip()
        comp_en = (row.get("Competition EN") or "").strip()
        home_zh = (row.get("Home ZH") or "").strip()
        away_zh = (row.get("Away ZH") or "").strip()
        if event_id and home_en and away_en:
            event_map[event_id] = (home_en, away_en, comp_en)
        if home_zh and home_en:
            zh_to_en.setdefault(normalize_zh(home_zh), home_en)
        if away_zh and away_en:
            zh_to_en.setdefault(normalize_zh(away_zh), away_en)

    for row in active_rows:
        zh = (row.get("中文名") or "").strip()
        en = (row.get("English Name") or "").strip()
        if zh and en:
            zh_to_en.setdefault(normalize_zh(zh), en)
        known = (row.get("All Known Aliases") or "").strip()
        if en and known:
            for alias in known.split("|"):
                alias = alias.strip()
                if alias and re.search(r"[\u3400-\u9fff]", alias):
                    zh_to_en.setdefault(normalize_zh(alias), en)

    return event_map, zh_to_en


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
    snapshot = fetch_csv(HKJC_SNAPSHOT_GID, "HKJC Source Snapshot")
    if not snapshot:
        return []

    fetched_times = [
        dt for dt in (parse_iso_utc(r.get("fetchedAt", "")) for r in snapshot)
        if dt is not None
    ]
    if not fetched_times:
        print("FATAL: HKJC snapshot has no parseable fetchedAt", file=sys.stderr)
        return []

    latest_fetch = max(fetched_times)
    now_utc = datetime.now(timezone.utc)
    age_minutes = (now_utc - latest_fetch).total_seconds() / 60
    print(
        f"HKJC_FRESHNESS latest={latest_fetch.isoformat()} age_min={age_minutes:.1f}",
        flush=True,
    )
    if age_minutes < -10 or age_minutes > MAX_SNAPSHOT_AGE_MINUTES:
        print(
            f"FATAL: HKJC snapshot stale/future age={age_minutes:.1f}m; "
            "ScraperAPI will not be called",
            file=sys.stderr,
        )
        return []

    bilingual = fetch_csv(BILINGUAL_MAP_GID, "HKJC Bilingual Map")
    active_alias = fetch_csv(ACTIVE_ALIAS_GID, "Active Team Alias")
    if not bilingual and not active_alias:
        print(
            "FATAL: no HKJC English alias source; ScraperAPI will not be called",
            file=sys.stderr,
        )
        return []

    event_map, zh_to_en = build_alias_maps(bilingual, active_alias)

    now = datetime.now(HKT)
    start = now - timedelta(minutes=LOOKBACK_MINUTES)
    end = now + timedelta(hours=LOOKAHEAD_HOURS)
    targets: list[dict[str, Any]] = []
    unresolved: list[str] = []

    for row in snapshot:
        kickoff_text = (row.get("kickoffHkt") or "").strip()
        try:
            kickoff = datetime.strptime(kickoff_text, "%Y-%m-%d %H:%M").replace(tzinfo=HKT)
        except ValueError:
            continue
        if kickoff < start or kickoff > end:
            continue

        had_h = (row.get("HAD H") or "").strip()
        had_d = (row.get("HAD D") or "").strip()
        had_a = (row.get("HAD A") or "").strip()
        if not (had_h and had_d and had_a):
            continue

        event_id = (row.get("HKJC #") or "").strip()
        home_zh = (row.get("home") or "").strip()
        away_zh = (row.get("away") or "").strip()
        league_zh = (row.get("competition") or "").strip()
        if not event_id or not home_zh or not away_zh:
            continue

        mapping_source = ""
        if event_id in event_map:
            home_en, away_en, _ = event_map[event_id]
            mapping_source = "event bilingual"
        else:
            home_en = zh_to_en.get(normalize_zh(home_zh), "")
            away_en = zh_to_en.get(normalize_zh(away_zh), "")
            mapping_source = "team alias"

        if not home_en or not away_en:
            unresolved.append(f"{event_id}:{home_zh} vs {away_zh}")
            continue

        targets.append({
            "match_date": kickoff.date().isoformat(),
            "kickoff_hkt": kickoff.strftime("%Y-%m-%d %H:%M"),
            "hkjc_event_id": event_id,
            "league_zh": league_zh,
            "home_zh": home_zh,
            "away_zh": away_zh,
            "home_en": home_en,
            "away_en": away_en,
            "had_home": had_h,
            "had_draw": had_d,
            "had_away": had_a,
            "mapping_source": mapping_source,
        })

    deduped: dict[str, dict[str, Any]] = {}
    for row in targets:
        deduped[row["hkjc_event_id"]] = row
    targets = sorted(
        deduped.values(),
        key=lambda r: (r["kickoff_hkt"], r["league_zh"], r["home_en"]),
    )

    if not targets:
        print(
            "FATAL: zero mappable HKJC HAD targets; ScraperAPI will not be called",
            file=sys.stderr,
        )
        return []

    write_targets(targets)
    dates = sorted({r["match_date"] for r in targets})
    print(
        f"HKJC_GATE targets={len(targets)} unresolved_alias={len(unresolved)} "
        f"dates={','.join(dates)} window_hours={LOOKAHEAD_HOURS}",
        flush=True,
    )
    for row in targets[:25]:
        print(
            f"  PICK {row['hkjc_event_id']} {row['kickoff_hkt']} | "
            f"{row['home_en']} vs {row['away_en']} | "
            f"HAD {row['had_home']}/{row['had_draw']}/{row['had_away']}",
            flush=True,
        )
    if len(targets) > 25:
        print(f"  ... {len(targets) - 25} more HKJC picks", flush=True)
    if unresolved:
        print("HKJC_ALIAS_GAPS " + " | ".join(unresolved[:15]), flush=True)
        if len(unresolved) > 15:
            print(f"HKJC_ALIAS_GAPS ... {len(unresolved) - 15} more", flush=True)
    return targets


def fetch_forebet_date(match_date: str) -> tuple[str | None, int | None]:
    if not SCRAPERAPI_KEY:
        print("FATAL: missing SCRAPERAPI_KEY GitHub Actions secret", file=sys.stderr)
        return None, None

    url = (
        "https://www.forebet.com/en/football-predictions/"
        f"predictions-1x2/{match_date}"
    )
    params = {"api_key": SCRAPERAPI_KEY, "url": url, "max_cost": MAX_COST}
    try:
        r = requests.get(SCRAPERAPI_URL, params=params, timeout=70)
    except Exception as exc:
        print(f"ERROR: ScraperAPI request failed for {match_date}: {exc}", file=sys.stderr)
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
        print(f"ERROR: ScraperAPI non-200 for {match_date}; no retry", file=sys.stderr)
        return None, credit_cost
    if "rcnt" not in r.text:
        print(f"ERROR: Forebet rows missing for {match_date}; no retry", file=sys.stderr)
        return None, credit_cost
    return r.text, credit_cost


def normalize_date(value: str, fallback: str) -> str:
    value = value.strip()
    if len(value) >= 10 and re.match(r"\d{4}-\d{2}-\d{2}", value[:10]):
        return value[:10]
    return fallback


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

        detail_url = ""
        anchor = row.find("a", href=re.compile(r"/(?:en/)?football/matches/", re.I))
        if anchor and anchor.get("href"):
            detail_url = urljoin("https://www.forebet.com", str(anchor.get("href"))).split("?")[0].split("#")[0]

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
            "prediction_1x2": text(row.select_one("span.forepr span")) or text(row.select_one(".forepr")),
            "predicted_score": text(row.select_one("div.ex_sc.tabonly")) or text(row.select_one(".predict_score, .ex_sc")),
            "avg_goals": text(row.select_one("div.avg_sc.tabonly")) or text(row.select_one(".avg_sc")),
            "odds_home": odds[0],
            "odds_draw": odds[1],
            "odds_away": odds[2],
            "prediction_ou25": "",
            "prob_over25": "",
            "prob_under25": "",
            "odds_over25": "",
            "odds_under25": "",
            "forebet_detail_url": detail_url,
        })
    return rows


def attach_hkjc_target(
    row: dict[str, Any],
    targets: list[dict[str, Any]],
    master: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    same_date = [t for t in targets if t["match_date"] == row["match_date"]]
    if not same_date:
        return None

    # One-for-all path: a previously verified Forebet name resolves directly
    # to the canonical HKJC English name. This avoids re-fuzzy-matching the
    # same clubs on every future fixture. All production callers get this path
    # automatically; callers do not need to pass a map explicitly.
    if master is None:
        master = forebet_master_map()
    if master:
        home_canonical = master.get(normalize_team(row["home_team"]))
        away_canonical = master.get(normalize_team(row["away_team"]))
        if home_canonical and away_canonical:
            direct = [
                t for t in same_date
                if normalize_team(t["home_en"]) == normalize_team(home_canonical)
                and normalize_team(t["away_en"]) == normalize_team(away_canonical)
            ]
            if len(direct) == 1:
                best = direct[0]
                out = dict(row)
                out.update({
                    "hkjc_event_id": best["hkjc_event_id"],
                    "hkjc_league": best["league_zh"],
                    "hkjc_home_team": best["home_en"],
                    "hkjc_away_team": best["away_en"],
                    "hkjc_home_zh": best["home_zh"],
                    "hkjc_away_zh": best["away_zh"],
                    "hkjc_kickoff_hkt": best["kickoff_hkt"],
                    "hkjc_had_home": best["had_home"],
                    "hkjc_had_draw": best["had_draw"],
                    "hkjc_had_away": best["had_away"],
                    "match_score": 1.0,
                })
                return out

    # Discovery-only fallback for genuinely new names. Once a successful
    # event mapping is persisted to team_name_master, future runs take the
    # direct path above instead of repeating this fuzzy search.
    best = None
    best_avg = 0.0
    best_home = 0.0
    best_away = 0.0
    for target in same_date:
        hs = team_score(row["home_team"], target["home_en"])
        aws = team_score(row["away_team"], target["away_en"])
        avg = (hs + aws) / 2
        if avg > best_avg:
            best = target
            best_avg = avg
            best_home = hs
            best_away = aws

    if best is None or best_home < 0.68 or best_away < 0.68 or best_avg < 0.76:
        return None

    out = dict(row)
    out.update({
        "hkjc_event_id": best["hkjc_event_id"],
        "hkjc_league": best["league_zh"],
        "hkjc_home_team": best["home_en"],
        "hkjc_away_team": best["away_en"],
        "hkjc_home_zh": best["home_zh"],
        "hkjc_away_zh": best["away_zh"],
        "hkjc_kickoff_hkt": best["kickoff_hkt"],
        "hkjc_had_home": best["had_home"],
        "hkjc_had_draw": best["had_draw"],
        "hkjc_had_away": best["had_away"],
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
    print("MODE=PUBLIC_HKJC_SHEET_GATE_THEN_FOREBET", flush=True)
    print(
        f"GATE_ONLY={int(GATE_ONLY)} SCRAPERAPI_MAX_COST={MAX_COST} "
        f"MAX_FOREBET_DATES={MAX_FOREBET_DATES}",
        flush=True,
    )

    targets = load_hkjc_targets()
    if not targets:
        return 2

    forebet_master = forebet_master_map()

    if GATE_ONLY:
        print(f"GATE_ONLY_PASS targets={len(targets)} scraperapi_calls=0", flush=True)
        return 0

    target_dates = sorted({r["match_date"] for r in targets})[:MAX_FOREBET_DATES]
    parsed: list[dict[str, Any]] = []
    total_known_cost = 0
    calls = 0

    for match_date in target_dates:
        html, cost = fetch_forebet_date(match_date)
        calls += 1
        if cost is not None:
            total_known_cost += cost
        if html is not None:
            parsed.extend(parse_forebet_rows(html, match_date))

    if not parsed:
        print("FATAL: no Forebet rows retrieved; existing CSV preserved", file=sys.stderr)
        return 2

    unique: dict[str, dict[str, Any]] = {}
    for row in parsed:
        selected = attach_hkjc_target(row, targets, forebet_master)
        if selected is None:
            continue
        key = selected["hkjc_event_id"]
        old = unique.get(key)
        if old is None or float(selected.get("match_score") or 0) > float(old.get("match_score") or 0):
            unique[key] = selected

    matched = sorted(
        unique.values(),
        key=lambda r: (r.get("hkjc_kickoff_hkt", ""), r.get("hkjc_event_id", "")),
    )
    if not matched:
        print(
            "FATAL: Forebet returned data but zero rows matched HKJC targets; "
            "existing CSV preserved",
            file=sys.stderr,
        )
        return 2

    good_probs = sum(
        1 for r in matched
        if all(isinstance(r.get(k), (int, float)) for k in ("prob_home", "prob_draw", "prob_away"))
    )
    if good_probs == 0:
        print("FATAL: matched HKJC rows have no usable probabilities", file=sys.stderr)
        return 2

    write_csv(matched)
    print(
        f"SUMMARY hkjc_targets={len(targets)} forebet_rows_seen={len(parsed)} "
        f"kept={len(matched)} probability_rows={good_probs} "
        f"scraperapi_calls={calls} known_credit_cost={total_known_cost}",
        flush=True,
    )
    print(f"WROTE {OUT} rows={len(matched)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
