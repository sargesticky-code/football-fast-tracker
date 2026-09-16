"""Enrich current HKJC-matched Forebet rows with O/U and corner predictions.

The routine uses only public Forebet pages through Jina Reader. It does not use
ScraperAPI. A generic 1X2 page is used to discover each match-detail URL; the
match page then supplies O/U 2.5 and corner U/O 9.5 signals for that exact event.
"""
from __future__ import annotations

import csv
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "forebet_current.csv"
JINA = "https://r.jina.ai/"
BASE = "https://www.forebet.com"
TIMEOUT = 90

EXTRA_FIELDS = [
    "ou_predicted_score",
    "corner_prediction",
    "corner_prob_under95",
    "corner_prob_over95",
    "corner_predicted_score",
    "avg_corners",
    "forebet_detail_url",
]


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def fetch_jina(url: str, html: bool) -> str | None:
    headers = {"x-timeout": "30", "User-Agent": "Mozilla/5.0"}
    if html:
        headers["x-respond-with"] = "html"
    try:
        r = requests.get(JINA + url, headers=headers, timeout=TIMEOUT)
    except Exception as exc:
        print(f"WARN Jina fetch failed url={url}: {exc}")
        return None
    if r.status_code != 200:
        print(f"WARN Jina status={r.status_code} url={url}")
        return None
    return r.text


def discover_links(rows: list[dict[str, str]]) -> dict[tuple[str, str], str]:
    """Build a generic Forebet team-pair -> match-detail URL map."""
    dates = sorted({(r.get("match_date") or "").strip() for r in rows if r.get("match_date")})
    urls = [
        f"https://www.forebet.com/en/football-predictions/predictions-1x2/{d}/by-league"
        for d in dates
    ]
    # Generic all-predictions pages cover rows omitted from the first dated payload.
    urls += [
        "https://www.forebet.com/en/football-predictions/predictions-1x2?start=2",
        "https://www.forebet.com/en/football-predictions?start=1",
    ]
    links: dict[tuple[str, str], str] = {}
    for url in urls:
        html = fetch_jina(url, html=True)
        if not html or "rcnt" not in html:
            continue
        soup = BeautifulSoup(html, "lxml")
        for box in soup.select("div.rcnt"):
            h = box.select_one("span.homeTeam span[itemprop='name']")
            a = box.select_one("span.awayTeam span[itemprop='name']")
            if not h or not a:
                continue
            anchor = box.select_one("a[href*='/football/matches/']")
            if anchor is None:
                # Forebet sometimes puts the preview URL on a team/match wrapper.
                anchor = next(
                    (x for x in box.select("a[href]") if "/football/matches/" in (x.get("href") or "")),
                    None,
                )
            if anchor is None:
                continue
            href = (anchor.get("href") or "").strip()
            if not href:
                continue
            links[(norm(h.get_text(" ", strip=True)), norm(a.get_text(" ", strip=True)))] = urljoin(BASE, href)
    print(f"FOREBET_DETAIL_LINKS discovered={len(links)} source_pages={len(urls)}")
    return links


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]


def parse_under_over_section(markdown: str, threshold: str) -> dict[str, str]:
    """Parse the first Under/Over block with a given threshold from one match page."""
    lines = _lines(markdown)
    start = -1
    for i in range(len(lines) - 1):
        if lines[i].casefold() == "under/over" and lines[i + 1] == threshold:
            start = i + 2
            break
    if start < 0:
        return {}

    pair_re = re.compile(r"^(\d{1,3})\s+(\d{1,3})$")
    score_re = re.compile(r"^(\d+)\s*-\s*(\d+)$")
    for i in range(start, min(len(lines), start + 45)):
        m = pair_re.match(lines[i])
        if not m:
            continue
        under, over = m.group(1), m.group(2)
        pred = ""
        score = ""
        avg = ""
        for j in range(i + 1, min(len(lines), i + 9)):
            low = lines[j].casefold()
            if not pred and (low.startswith("under") or low.startswith("over")):
                pred = "Under" if low.startswith("under") else "Over"
                continue
            sm = score_re.match(lines[j])
            if sm and not score:
                score = f"{sm.group(1)}-{sm.group(2)}"
                continue
            if score and re.fullmatch(r"\d+(?:\.\d+)?", lines[j]):
                avg = lines[j]
                break
        if pred:
            return {"under": under, "over": over, "prediction": pred, "score": score, "avg": avg}
    return {}


def read_feed() -> tuple[list[dict[str, str]], list[str]]:
    with FEED.open(encoding="utf-8-sig", newline="") as fh:
        r = csv.DictReader(fh)
        return list(r), list(r.fieldnames or [])


def main() -> int:
    if not FEED.exists():
        raise SystemExit(f"missing {FEED}")
    rows, fields = read_feed()
    if not rows:
        raise SystemExit("zero Forebet rows to enrich")
    for f in EXTRA_FIELDS:
        if f not in fields:
            fields.append(f)

    links = discover_links(rows)
    detail_cache: dict[str, str | None] = {}
    ou_count = corner_count = link_count = 0

    for idx, row in enumerate(rows):
        key = (norm(row.get("home_team", "")), norm(row.get("away_team", "")))
        url = links.get(key, "")
        row["forebet_detail_url"] = url
        if not url:
            continue
        link_count += 1
        if url not in detail_cache:
            detail_cache[url] = fetch_jina(url, html=False)
            # Keep the free anonymous reader comfortably below burst limits.
            time.sleep(0.8)
        md = detail_cache[url] or ""
        if not md:
            continue

        ou = parse_under_over_section(md, "2.5")
        if ou:
            row["prediction_ou25"] = ou["prediction"]
            # Existing feed schema is Over first, Under second.
            row["prob_over25"] = ou["over"]
            row["prob_under25"] = ou["under"]
            row["ou_predicted_score"] = ou["score"]
            if not row.get("avg_goals") and ou.get("avg"):
                row["avg_goals"] = ou["avg"]
            ou_count += 1

        corners = parse_under_over_section(md, "9.5")
        if corners:
            row["corner_prediction"] = corners["prediction"]
            row["corner_prob_under95"] = corners["under"]
            row["corner_prob_over95"] = corners["over"]
            row["corner_predicted_score"] = corners["score"]
            row["avg_corners"] = corners["avg"]
            corner_count += 1

    tmp = FEED.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    tmp.replace(FEED)
    print(
        f"FOREBET_MARKETS rows={len(rows)} detail_links={link_count} "
        f"ou25={ou_count} corners95={corner_count} jina_calls={len(detail_cache)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
