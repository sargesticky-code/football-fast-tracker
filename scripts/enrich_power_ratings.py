"""Enrich the HKJC-gated Forebet feed with independent Opta club power ratings.

Forebet remains the match-probability model. Opta supplies a second, global
team-strength signal on a 0-100 scale. The Opta dataviz bundle contains men's
rankings for 10,000+ clubs, so this works across Europe, the Americas, Asia and
other HKJC competitions rather than recreating FiveThirtyEight's narrower feed.

Failure policy:
- never destroy a valid Forebet feed;
- retain the last good Opta snapshot when a refresh temporarily fails;
- never force an ambiguous team-name match.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

import requests

SOURCE_URL = "https://dataviz.theanalyst.com/opta-power-rankings/index.js"
FEED_PATH = Path("data/forebet_current.csv")
HKJC_PATH = Path("data/hkjc_current.csv")
RATINGS_PATH = Path("data/power_ratings.csv")
HKJC_POWER_PATH = Path("data/hkjc_power_current.csv")
SOURCE = "Opta Power Rankings"
REQUEST_TIMEOUT = 45
MIN_EXPECTED_RATINGS = 5000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://theanalyst.com/",
}

# Source/HKJC naming variants that are common in the current production feed.
# Exact normalized matches are always preferred; fuzzy matching is conservative.
ALIASES = {
    "puebla": ["puebla", "puebla fc", "club puebla"],
    "puebla fc": ["puebla", "puebla fc", "club puebla"],
    "toluca": ["toluca", "toluca fc", "deportivo toluca", "deportivo toluca fc"],
    "deportivo toluca": ["toluca", "toluca fc", "deportivo toluca", "deportivo toluca fc"],
    "dorados": ["dorados", "dorados de sinaloa", "dorados sinaloa"],
    "dorados sinaloa": ["dorados", "dorados de sinaloa", "dorados sinaloa"],
    "cancun": ["cancun", "cancun fc"],
    "cancun fc": ["cancun", "cancun fc"],
    "jeonbuk motors": ["jeonbuk motors", "jeonbuk hyundai motors", "jeonbuk hyundai"],
    "jeonbuk hyundai": ["jeonbuk motors", "jeonbuk hyundai motors", "jeonbuk hyundai"],
    "fc seoul": ["fc seoul", "seoul"],
    "persib bandung": ["persib bandung", "persib"],
    "port fc": ["port fc", "port", "port authority of thailand"],
    "vissel kobe": ["vissel kobe", "kobe"],
    "the cong": ["the cong", "the cong viettel", "viettel", "viettel fc"],
    "viettel": ["the cong", "the cong viettel", "viettel", "viettel fc"],
    "melbourne victory": ["melbourne victory", "melbourne victory fc"],
    "kashiwa reysol": ["kashiwa reysol", "kashiwa"],
    "grasshoppers": ["grasshoppers", "grasshopper club zurich", "grasshopper zurich"],
    "sion": ["sion", "fc sion"],
    "vallecano": ["rayo vallecano", "vallecano"],
    "willem ii": ["willem ii", "willem ii tilburg"],
    "al hilal": ["al hilal", "al hilal saudi", "al hilal riyadh"],
    "al gharafa": ["al gharafa", "al gharafa sc"],
    "bristol city": ["bristol city", "bristol city fc"],
    "lincoln city": ["lincoln city", "lincoln city fc"],
    "middlesbrough": ["middlesbrough", "middlesbrough fc"],
    "west ham": ["west ham", "west ham united"],
    "heart of midlothian": ["heart of midlothian", "hearts"],
    "ipswich": ["ipswich", "ipswich town"],
    "tottenham": ["tottenham", "tottenham hotspur"],
    "real madrid": ["real madrid", "real madrid cf"],
    "sao paulo": ["sao paulo", "sao paulo fc"],
    "boca juniors": ["boca juniors", "ca boca juniors"],
}

GENERIC_TOKENS = {
    "fc", "cf", "sc", "afc", "club", "football", "soccer", "fk", "ac",
    "de", "the",
}


@dataclass(frozen=True)
class Rating:
    club: str
    country: str
    score: float
    rank: int | None
    updated: str
    opta_id: str = ""
    league: str = ""


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def compact(value: str) -> str:
    return norm(value).replace(" ", "")


def core_tokens(value: str) -> tuple[str, ...]:
    return tuple(t for t in norm(value).split() if t not in GENERIC_TOKENS)


def _extract_all_json_parse(js_text: str) -> list[str]:
    """Return array payloads embedded as JSON.parse(`[ ... ]`) in Opta JS."""
    pattern = r'JSON\.parse\(`(\[[^`]*\])`\)'
    matches = re.findall(pattern, js_text)
    # Opta's `comps` strings may double-escape quotes. Collapse the extra slash
    # before json.loads, matching the resilient public parsers for this bundle.
    dbl_esc = chr(92) + chr(92) + chr(34)
    sgl_esc = chr(92) + chr(34)
    return [raw.replace(dbl_esc, sgl_esc) for raw in matches]


def _ranking_entries(js_text: str) -> list[dict]:
    """Find the men's ranking block without relying on minified variable names."""
    candidates: list[list[dict]] = []
    for raw in _extract_all_json_parse(js_text):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            continue
        keys = set(data[0])
        if {"contestantName", "currentRating"}.issubset(keys):
            candidates.append(data)
    if not candidates:
        raise RuntimeError("Opta men's ranking JSON block not found")
    # Men's dataset is much larger than the women's/search blocks. Selecting
    # the largest valid ranking block is resilient to minified variable renames.
    return max(candidates, key=len)


def scrape_ratings() -> list[Rating]:
    response = requests.get(SOURCE_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    entries = _ranking_entries(response.text)
    fetched = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    out: list[Rating] = []
    for e in entries:
        club = str(e.get("contestantName") or e.get("contestantClubName") or "").strip()
        try:
            score = float(e.get("currentRating"))
        except (TypeError, ValueError):
            continue
        if not club or not (0 <= score <= 100):
            continue
        try:
            rank = int(e.get("rank") or e.get("currentGlobalRank") or 0) or None
        except (TypeError, ValueError):
            rank = None
        out.append(
            Rating(
                club=club,
                country=str(e.get("country") or "").strip(),
                score=score,
                rank=rank,
                updated=fetched,
                opta_id=str(e.get("contestantId") or ""),
                league=str(e.get("domesticLeagueName") or "").strip(),
            )
        )

    # Deduplicate by normalized club name, retaining the highest-rated instance.
    dedup: dict[str, Rating] = {}
    for row in out:
        key = norm(row.club)
        prev = dedup.get(key)
        if prev is None or row.score > prev.score:
            dedup[key] = row

    ratings = sorted(dedup.values(), key=lambda r: (r.rank or 10**9, -r.score, r.club))
    if len(ratings) < MIN_EXPECTED_RATINGS:
        raise RuntimeError(f"Opta rating scrape suspiciously small: {len(ratings)} clubs")
    return ratings


def write_snapshot(ratings: Iterable[Rating]) -> None:
    RATINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RATINGS_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "club", "country", "rating", "updated", "source", "opta_id", "league"])
        for r in ratings:
            w.writerow([
                r.rank or "", r.club, r.country, f"{r.score:.6f}", r.updated,
                SOURCE, r.opta_id, r.league,
            ])
    tmp.replace(RATINGS_PATH)


def load_snapshot() -> list[Rating]:
    if not RATINGS_PATH.exists():
        return []
    out: list[Rating] = []
    with RATINGS_PATH.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                score_raw = row.get("rating") or row.get("points")
                out.append(
                    Rating(
                        club=row["club"],
                        country=row.get("country", ""),
                        score=float(score_raw),
                        rank=int(row["rank"]) if row.get("rank") else None,
                        updated=row.get("updated", ""),
                        opta_id=row.get("opta_id", ""),
                        league=row.get("league", ""),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
    return out


def variants(name: str) -> list[str]:
    n = norm(name)
    vals = [n]
    vals.extend(ALIASES.get(n, []))
    return list(dict.fromkeys(norm(v) for v in vals if v))


def match_rating(name: str, ratings: list[Rating]) -> tuple[Rating | None, float]:
    if not name or not ratings:
        return None, 0.0

    by_norm = {norm(r.club): r for r in ratings}
    by_compact = {compact(r.club): r for r in ratings}

    for v in variants(name):
        if v in by_norm:
            return by_norm[v], 1.0
        c = v.replace(" ", "")
        if c in by_compact:
            return by_compact[c], 0.99

    target = norm(name)
    target_core = set(core_tokens(name))
    best: tuple[float, Rating] | None = None
    second = 0.0

    for r in ratings:
        cand = norm(r.club)
        cand_core = set(core_tokens(r.club))
        seq = SequenceMatcher(None, target, cand).ratio()
        jac = (len(target_core & cand_core) / len(target_core | cand_core)) if (target_core | cand_core) else 0.0
        subset = 1.0 if target_core and (target_core <= cand_core or cand_core <= target_core) else 0.0
        score = max(seq, 0.82 * jac + 0.18 * subset)
        if best is None or score > best[0]:
            if best is not None:
                second = best[0]
            best = (score, r)
        elif score > second:
            second = score

    if best is None:
        return None, 0.0
    score, rating = best
    # High threshold + separation from runner-up prevents accidental clubs with
    # similar names from being treated as the same team.
    if score >= 0.90 and score - second >= 0.025:
        return rating, score
    return None, score


def enrich_feed(ratings: list[Rating]) -> tuple[int, int]:
    if not FEED_PATH.exists():
        raise RuntimeError(f"missing {FEED_PATH}")

    with FEED_PATH.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = list(reader.fieldnames or [])

    extra = [
        "power_home", "power_away", "power_home_name", "power_away_name",
        "power_source", "power_updated", "power_home_match", "power_away_match",
    ]
    for field in extra:
        if field not in fields:
            fields.append(field)

    matched_sides = 0
    total_sides = 0
    for row in rows:
        home = row.get("hkjc_home_team") or row.get("home_team") or ""
        away = row.get("hkjc_away_team") or row.get("away_team") or ""
        hr, hs = match_rating(home, ratings)
        ar, ass = match_rating(away, ratings)
        total_sides += 2
        matched_sides += int(hr is not None) + int(ar is not None)

        row["power_home"] = f"{hr.score:.4f}" if hr else ""
        row["power_away"] = f"{ar.score:.4f}" if ar else ""
        row["power_home_name"] = hr.club if hr else ""
        row["power_away_name"] = ar.club if ar else ""
        row["power_source"] = SOURCE if (hr or ar) else ""
        row["power_updated"] = hr.updated if hr else (ar.updated if ar else "")
        row["power_home_match"] = f"{hs:.3f}" if hr else ""
        row["power_away_match"] = f"{ass:.3f}" if ar else ""

    tmp = FEED_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(FEED_PATH)
    return matched_sides, total_sides



def write_hkjc_power_feed(ratings: list[Rating]) -> tuple[int, int]:
    """Build Opta strength by HKJC event, independent of Forebet availability."""
    if not HKJC_PATH.exists():
        raise RuntimeError(f"missing {HKJC_PATH}")

    with HKJC_PATH.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    fields = [
        "fetched_at_hkt", "hkjc_event_id", "kickoff_hkt", "tournament",
        "home_en", "away_en", "home_rating", "away_rating",
        "home_opta_name", "away_opta_name", "home_match_confidence",
        "away_match_confidence", "home_rank", "away_rank",
        "coverage", "source", "power_updated",
    ]
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out = []
    matched_sides = 0
    total_sides = 0

    for row in rows:
        event_id = str(row.get("hkjc_event_id") or "").strip()
        home = str(row.get("home_en") or "").strip()
        away = str(row.get("away_en") or "").strip()
        if not event_id or not home or not away:
            continue

        hr, hs = match_rating(home, ratings)
        ar, ass = match_rating(away, ratings)
        matched_sides += int(hr is not None) + int(ar is not None)
        total_sides += 2

        if hr and ar:
            coverage = "BOTH"
        elif hr:
            coverage = "HOME_ONLY"
        elif ar:
            coverage = "AWAY_ONLY"
        else:
            coverage = "NONE"

        out.append({
            "fetched_at_hkt": now,
            "hkjc_event_id": event_id,
            "kickoff_hkt": row.get("kickoff_hkt", ""),
            "tournament": row.get("tournament", ""),
            "home_en": home,
            "away_en": away,
            "home_rating": f"{hr.score:.4f}" if hr else "",
            "away_rating": f"{ar.score:.4f}" if ar else "",
            "home_opta_name": hr.club if hr else "",
            "away_opta_name": ar.club if ar else "",
            "home_match_confidence": f"{hs:.3f}" if hr else "",
            "away_match_confidence": f"{ass:.3f}" if ar else "",
            "home_rank": hr.rank if hr and hr.rank else "",
            "away_rank": ar.rank if ar and ar.rank else "",
            "coverage": coverage,
            "source": SOURCE,
            "power_updated": (hr.updated if hr else (ar.updated if ar else now)),
        })

    HKJC_POWER_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HKJC_POWER_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out)
    tmp.replace(HKJC_POWER_PATH)
    return matched_sides, total_sides

def main() -> int:
    try:
        ratings = scrape_ratings()
        write_snapshot(ratings)
        print(f"Opta power ratings refreshed: {len(ratings)} clubs")
    except Exception as exc:
        print(f"WARNING Opta rating refresh failed: {exc}")
        ratings = load_snapshot()
        print(f"using cached power-rating snapshot: {len(ratings)} clubs")

    matched, total = enrich_feed(ratings)
    print(f"Opta power enrichment coverage: {matched}/{total} Forebet team-sides")
    hkjc_matched, hkjc_total = write_hkjc_power_feed(ratings)
    print(
        f"Opta HKJC-event coverage: {hkjc_matched}/{hkjc_total} team-sides "
        f"wrote={HKJC_POWER_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
