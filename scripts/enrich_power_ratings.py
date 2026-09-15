"""Enrich the current HKJC-gated Forebet feed with independent club strength ratings.

Primary source: FootballDatabase world club ranking.  The source is intentionally
kept separate from Forebet: Forebet supplies match probabilities, while this
module supplies a second, result-based team-strength signal.

Failure policy:
- never destroy the Forebet feed;
- keep the last good rating snapshot when the source is temporarily unavailable;
- leave a rating blank rather than forcing a low-confidence team-name match.
"""
from __future__ import annotations

import csv
import re
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://footballdatabase.com/ranking/world/{page}"
FEED_PATH = Path("data/forebet_current.csv")
RATINGS_PATH = Path("data/power_ratings.csv")
SOURCE = "FootballDatabase"
MAX_PAGES_FALLBACK = 80
MAX_PAGES_HARD = 140
REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Only high-value aliases are hard-coded.  Everything else goes through exact
# normalization first, then a conservative fuzzy matcher.
ALIASES = {
    "puebla": ["puebla", "puebla fc"],
    "puebla fc": ["puebla", "puebla fc"],
    "toluca": ["toluca", "toluca fc", "deportivo toluca"],
    "deportivo toluca": ["toluca", "toluca fc", "deportivo toluca"],
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
}

GENERIC_TOKENS = {
    "fc", "cf", "sc", "afc", "club", "football", "soccer", "fk", "ac",
}


@dataclass(frozen=True)
class Rating:
    club: str
    country: str
    points: int
    rank: int | None
    updated: str


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


def parse_updated(text: str) -> str:
    m = re.search(r"Updated after matches played on\s+([^\n<]+)", text, re.I)
    return m.group(1).strip() if m else ""


def parse_page(html: str) -> tuple[list[Rating], str, int | None]:
    soup = BeautifulSoup(html, "lxml")
    page_text = soup.get_text("\n", strip=True)
    updated = parse_updated(page_text)

    max_page = None
    for a in soup.find_all("a", href=True):
        m = re.search(r"/ranking/world/(\d+)", a["href"])
        if m:
            n = int(m.group(1))
            max_page = n if max_page is None else max(max_page, n)

    chosen = None
    for table in soup.find_all("table"):
        header = " | ".join(th.get_text(" ", strip=True) for th in table.find_all("th"))
        h = header.casefold()
        if "points" in h and ("club" in h or "country" in h):
            chosen = table
            break
    if chosen is None:
        return [], updated, max_page

    rows: list[Rating] = []
    for tr in chosen.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 3:
            continue

        # Rank is normally the first column.
        rank = None
        m_rank = re.search(r"\d+", cells[0].get_text(" ", strip=True))
        if m_rank:
            rank = int(m_rank.group())

        club_cell = cells[1]
        link = club_cell.find("a")
        club = link.get_text(" ", strip=True) if link else ""
        if not club:
            # Fallback for layout changes: use text before a country badge/span.
            club = club_cell.get_text(" ", strip=True)
        club = re.sub(r"\s+", " ", club).strip()
        if not club:
            continue

        country = ""
        spans = club_cell.find_all("span")
        if spans:
            candidates = [s.get_text(" ", strip=True) for s in spans if s.get_text(" ", strip=True)]
            if candidates:
                country = candidates[-1]

        # Points is normally the third column; keep a fallback in case a layout
        # column is inserted.
        points = None
        for cell in cells[2:5]:
            txt = cell.get_text(" ", strip=True).replace(",", "")
            m = re.search(r"(?<!\d)(\d{3,4})(?!\d)", txt)
            if m:
                points = int(m.group(1))
                break
        if points is None:
            continue

        rows.append(Rating(club=club, country=country, points=points, rank=rank, updated=updated))
    return rows, updated, max_page


def get_with_retry(session: requests.Session, url: str) -> requests.Response:
    last = None
    for attempt in range(3):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def scrape_ratings() -> list[Rating]:
    session = requests.Session()
    session.headers.update(HEADERS)

    first = get_with_retry(session, BASE_URL.format(page=1))
    first_rows, _, discovered_max = parse_page(first.text)
    if not first_rows:
        raise RuntimeError("FootballDatabase ranking table not found on page 1")

    max_page = discovered_max or MAX_PAGES_FALLBACK
    max_page = max(1, min(max_page, MAX_PAGES_HARD))
    all_rows = list(first_rows)
    empty_streak = 0

    for page in range(2, max_page + 1):
        r = get_with_retry(session, BASE_URL.format(page=page))
        rows, _, _ = parse_page(r.text)
        if not rows:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
            all_rows.extend(rows)
        time.sleep(0.08)

    # Deduplicate by normalized club name, keeping the best (lowest) rank.
    dedup: dict[str, Rating] = {}
    for row in all_rows:
        key = norm(row.club)
        prev = dedup.get(key)
        if prev is None or ((row.rank or 10**9) < (prev.rank or 10**9)):
            dedup[key] = row

    ratings = sorted(dedup.values(), key=lambda r: (r.rank or 10**9, r.club))
    if len(ratings) < 200:
        raise RuntimeError(f"rating scrape suspiciously small: {len(ratings)} rows")
    return ratings


def write_snapshot(ratings: Iterable[Rating]) -> None:
    RATINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RATINGS_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "club", "country", "points", "updated", "source"])
        for r in ratings:
            w.writerow([r.rank or "", r.club, r.country, r.points, r.updated, SOURCE])
    tmp.replace(RATINGS_PATH)


def load_snapshot() -> list[Rating]:
    if not RATINGS_PATH.exists():
        return []
    out: list[Rating] = []
    with RATINGS_PATH.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                out.append(
                    Rating(
                        club=row["club"],
                        country=row.get("country", ""),
                        points=int(float(row["points"])),
                        rank=int(row["rank"]) if row.get("rank") else None,
                        updated=row.get("updated", ""),
                    )
                )
            except (KeyError, ValueError):
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
    # Conservative: no ambiguous fuzzy matches.
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
        if hr:
            matched_sides += 1
        if ar:
            matched_sides += 1

        row["power_home"] = hr.points if hr else ""
        row["power_away"] = ar.points if ar else ""
        row["power_home_name"] = hr.club if hr else ""
        row["power_away_name"] = ar.club if ar else ""
        row["power_source"] = SOURCE if (hr or ar) else ""
        row["power_updated"] = (hr.updated if hr else (ar.updated if ar else ""))
        row["power_home_match"] = f"{hs:.3f}" if hr else ""
        row["power_away_match"] = f"{ass:.3f}" if ar else ""

    tmp = FEED_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(FEED_PATH)
    return matched_sides, total_sides


def main() -> int:
    ratings: list[Rating]
    try:
        ratings = scrape_ratings()
        write_snapshot(ratings)
        print(f"power ratings refreshed: {len(ratings)} clubs")
    except Exception as exc:  # keep last good snapshot rather than killing Forebet
        print(f"WARNING power-rating refresh failed: {exc}")
        ratings = load_snapshot()
        print(f"using cached power-rating snapshot: {len(ratings)} clubs")

    matched, total = enrich_feed(ratings)
    print(f"power enrichment coverage: {matched}/{total} team-sides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
