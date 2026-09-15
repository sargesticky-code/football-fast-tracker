"""Filter Bet365 Playwright output down to current HKJC-bettable 1X2 fixtures.

Bet365 is a secondary market benchmark, never the production fixture authority.
The expensive browser scraper is only launched when current HKJC targets contain
a supported competition.  Output is one row per canonical HKJC FBxxxx id.
"""
from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")
ROOT = Path(__file__).resolve().parent.parent
TARGETS = ROOT / "data" / "hkjc_targets.csv"
OUT = ROOT / "data" / "bet365_current.csv"
COLUMNS = [
    "fetched_at_hkt", "hkjc_event_id", "match_date", "kickoff_hkt", "league",
    "home", "away", "bet365_home", "bet365_draw", "bet365_away",
    "bet365_fixture_id", "match_quality", "source",
]

ALIASES = {
    "rayo vallecano": "rayo vallecano",
    "vallecano": "rayo vallecano",
    "athletic bilbao": "athletic club",
    "athletic club bilbao": "athletic club",
    "atletico madrid": "atletico madrid",
    "atletico de madrid": "atletico madrid",
    "real betis": "betis",
    "betis": "betis",
    "real sociedad": "real sociedad",
}


def norm(value: str) -> str:
    value = "".join(c for c in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    for token in (" fc", " cf", " afc", " club de futbol"):
        if value.endswith(token):
            value = value[: -len(token)].strip()
    return ALIASES.get(value, value)


def score(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if min(len(a), len(b)) >= 5 and (a in b or b in a):
        return 0.95
    return SequenceMatcher(None, a, b).ratio()


def load_targets() -> list[dict[str, str]]:
    if not TARGETS.exists():
        return []
    with TARGETS.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def detect_supported(targets: list[dict[str, str]]) -> list[str]:
    found: set[str] = set()
    for row in targets:
        label = (row.get("league_zh") or "").casefold()
        compact = re.sub(r"\s+", "", label)
        if any(x in compact for x in ("西班牙甲", "laliga", "la liga", "西甲")):
            found.add("spain")
        if any(x in compact for x in ("歐霸", "europaleague", "europa league", "uel")):
            found.add("uel")
    return sorted(found)


def write(rows: list[dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(OUT)


def normalize(raw_paths: list[Path], targets: list[dict[str, str]]) -> list[dict]:
    raw: list[dict[str, str]] = []
    for path in raw_paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            raw.extend(csv.DictReader(fh))

    # market id 40 is Bet365's full-time 1X2 market in the validated scraper.
    raw = [r for r in raw if str(r.get("mercado_id") or "") == "40"]
    by_fixture: dict[str, list[dict[str, str]]] = {}
    for r in raw:
        by_fixture.setdefault(r.get("fixture_id") or "", []).append(r)

    fetched = datetime.now(HKT).replace(microsecond=0).isoformat()
    out: list[dict] = []
    used_targets: set[str] = set()

    for fixture_id, rows in by_fixture.items():
        if not fixture_id or not rows:
            continue
        sample = rows[0]
        rh, ra = sample.get("local", ""), sample.get("visitante", "")
        best = None
        best_quality = 0.0
        for target in targets:
            event_id = target.get("hkjc_event_id") or ""
            if event_id in used_targets:
                continue
            hs = score(rh, target.get("home_en", ""))
            aws = score(ra, target.get("away_en", ""))
            quality = (hs + aws) / 2
            if hs >= 0.70 and aws >= 0.70 and quality > best_quality:
                best, best_quality = target, quality
        if best is None or best_quality < 0.80:
            continue

        prices: dict[str, float] = {}
        for r in rows:
            selection = norm(r.get("seleccion", ""))
            try:
                price = float(r.get("cuota", ""))
            except (TypeError, ValueError):
                continue
            if score(selection, rh) >= 0.80:
                prices["H"] = price
            elif selection in {"empate", "draw"}:
                prices["D"] = price
            elif score(selection, ra) >= 0.80:
                prices["A"] = price
        if not all(k in prices for k in ("H", "D", "A")):
            continue

        used_targets.add(best["hkjc_event_id"])
        out.append({
            "fetched_at_hkt": fetched,
            "hkjc_event_id": best["hkjc_event_id"],
            "match_date": best.get("match_date", ""),
            "kickoff_hkt": best.get("kickoff_hkt", ""),
            "league": best.get("league_zh", ""),
            "home": best.get("home_en", ""),
            "away": best.get("away_en", ""),
            "bet365_home": prices["H"],
            "bet365_draw": prices["D"],
            "bet365_away": prices["A"],
            "bet365_fixture_id": fixture_id,
            "match_quality": round(best_quality, 3),
            "source": "Bet365 Playwright",
        })

    out.sort(key=lambda r: (r["kickoff_hkt"], r["hkjc_event_id"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detect", action="store_true")
    ap.add_argument("--empty", action="store_true")
    ap.add_argument("--raw", action="append", default=[])
    args = ap.parse_args()

    targets = load_targets()
    if args.detect:
        print(",".join(detect_supported(targets)))
        return 0
    if args.empty:
        write([])
        print("BET365_FILTER rows=0 reason=no_supported_hkjc_competitions")
        return 0

    rows = normalize([Path(p) for p in args.raw], targets)
    write(rows)
    print(f"BET365_FILTER targets={len(targets)} rows={len(rows)}")
    if args.raw and not rows:
        raise SystemExit("Bet365 scrape completed but zero rows matched HKJC targets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
