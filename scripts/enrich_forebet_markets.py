"""Batch-enrich HKJC-matched Forebet rows with O/U 2.5 and corners 9.5.

Durable routine:
- zero ScraperAPI credits;
- one Jina Markdown request per market per Forebet date;
- exact Forebet home/away names from the already-matched 1X2 feed are the join key;
- no league-specific or event-specific routes;
- rolling archive preserves earlier secondary-market values if a later batch omits them.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "forebet_current.csv"
JINA = "https://r.jina.ai/"
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

PAIR_RE = re.compile(r"^(\d{1,3})\s+(\d{1,3})$")
SCORE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")
NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def text_score(home: str, away: str) -> str:
    """Use spaces around the dash so Google IMPORTDATA keeps a score as text."""
    return f"{home} - {away}"


def fetch_markdown(url: str, label: str) -> str | None:
    try:
        r = requests.get(
            JINA + url,
            headers={"x-timeout": "30", "User-Agent": "Mozilla/5.0"},
            timeout=TIMEOUT,
        )
    except Exception as exc:
        print(f"WARN Jina {label} failed: {exc}")
        return None
    print(f"FOREBET_MARKET_JINA label={label} status={r.status_code} bytes={len(r.text)}")
    if r.status_code != 200:
        return None
    return r.text


def lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]


def find_fixture_index(page_lines: list[str], home: str, away: str) -> int:
    h, a = norm(home), norm(away)
    if not h or not a:
        return -1
    for i, line in enumerate(page_lines):
        n = norm(line)
        if h in n and a in n:
            return i
    return -1


def parse_row_window(page_lines: list[str], start: int) -> dict[str, str]:
    """Parse Forebet list-page row after its fixture-link line.

    Expected sequence is probability pair, Under/Over prediction, predicted score,
    then average. Extra image/weather/coefficient lines after those fields are ignored.
    """
    if start < 0:
        return {}
    pair = None
    pred = ""
    score = ""
    avg = ""
    for line in page_lines[start + 1 : min(len(page_lines), start + 18)]:
        if pair is None:
            m = PAIR_RE.match(line)
            if m:
                pair = (m.group(1), m.group(2))
                continue
        if pair is not None and not pred:
            low = line.casefold()
            if low.startswith("under"):
                pred = "Under"
                continue
            if low.startswith("over"):
                pred = "Over"
                continue
        if pair is not None and pred and not score:
            m = SCORE_RE.match(line)
            if m:
                score = text_score(m.group(1), m.group(2))
                continue
        if score and NUMBER_RE.match(line):
            avg = line
            break
    if not pair or not pred:
        return {}
    return {
        "under": pair[0],
        "over": pair[1],
        "prediction": pred,
        "score": score,
        "avg": avg,
    }


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

    dates = sorted({(r.get("match_date") or "").strip() for r in rows if r.get("match_date")})
    ou_pages: dict[str, list[str]] = {}
    corner_pages: dict[str, list[str]] = {}
    calls = 0
    for d in dates:
        ou_url = f"https://www.forebet.com/en/football-predictions/under-over-25-goals/{d}/by-league"
        corner_url = f"https://www.forebet.com/en/football-predictions/corners/{d}"
        ou = fetch_markdown(ou_url, f"ou25_{d}")
        calls += 1
        corners = fetch_markdown(corner_url, f"corners95_{d}")
        calls += 1
        ou_pages[d] = lines(ou or "")
        corner_pages[d] = lines(corners or "")

    ou_count = corner_count = 0
    for row in rows:
        d = (row.get("match_date") or "").strip()
        home = row.get("home_team", "")
        away = row.get("away_team", "")

        ou = parse_row_window(ou_pages.get(d, []), find_fixture_index(ou_pages.get(d, []), home, away))
        if ou:
            row["prediction_ou25"] = ou["prediction"]
            row["prob_over25"] = ou["over"]
            row["prob_under25"] = ou["under"]
            row["ou_predicted_score"] = ou["score"]
            if not row.get("avg_goals") and ou.get("avg"):
                row["avg_goals"] = ou["avg"]
            ou_count += 1

        corners = parse_row_window(
            corner_pages.get(d, []),
            find_fixture_index(corner_pages.get(d, []), home, away),
        )
        if corners:
            row["corner_prediction"] = corners["prediction"]
            row["corner_prob_under95"] = corners["under"]
            row["corner_prob_over95"] = corners["over"]
            row["corner_predicted_score"] = corners["score"]
            row["avg_corners"] = corners["avg"]
            corner_count += 1

        # Reserved for compatibility/debugging; routine enrichment is batch-based.
        row["forebet_detail_url"] = ""

    tmp = FEED.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(FEED)

    print(
        f"FOREBET_MARKETS_BATCH rows={len(rows)} dates={len(dates)} "
        f"ou25={ou_count} corners95={corner_count} jina_calls={calls} scraperapi_credits=0"
    )
    if ou_count == 0:
        raise SystemExit("zero Forebet O/U rows parsed")
    if corner_count == 0:
        raise SystemExit("zero Forebet corner rows parsed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
