"""Batch-enrich HKJC-matched Forebet rows with O/U 2.5 and corners 9.5.

Durable routine:
- zero ScraperAPI credits;
- one fresh full-HTML Jina request per market per Forebet date;
- exact Forebet home/away names from the already-matched 1X2 feed are the join key;
- tolerant text parsing handles teams/probabilities split across HTML text nodes;
- no league-specific or event-specific routes;
- archived secondary-market values are preserved by restore_active_forebet.py when
  a later Forebet page omits a fixture after kickoff;
- if a fixture is visibly listed on the corner page but cannot be parsed, fail the
  run instead of accepting a silent parser gap.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "forebet_current.csv"
JINA = "https://r.jina.ai/"
TIMEOUT = 90
MIN_PAGE_TEXT = 5_000

EXTRA_FIELDS = [
    "ou_predicted_score",
    "corner_prediction",
    "corner_prob_under95",
    "corner_prob_over95",
    "corner_predicted_score",
    "avg_corners",
    "forebet_detail_url",
]

SCORE_SEARCH_RE = re.compile(r"(\d+)\s*-\s*(\d+)")
DECIMAL_SEARCH_RE = re.compile(r"(?<!\d)(\d+\.\d+)(?!\d)")
INTEGER_ONLY_RE = re.compile(r"^\d{1,3}%?$")


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


def fetch_page_text(url: str, label: str) -> str | None:
    """Ask Jina for the full rendered HTML, then flatten it locally to text.

    The 1X2 production path already uses x-respond-with=html successfully.  Using
    Jina's default Markdown here produced much smaller responses and silently
    omitted valid Forebet corner rows, so secondary markets now use the same full
    HTML strategy.
    """
    try:
        r = requests.get(
            JINA + url,
            headers={
                "x-respond-with": "html",
                "x-timeout": "30",
                "User-Agent": "Mozilla/5.0",
                "X-No-Cache": "true",
                "X-Cache-Tolerance": "0",
            },
            timeout=TIMEOUT,
        )
    except Exception as exc:
        print(f"WARN Jina {label} failed: {exc}")
        return None
    if r.status_code != 200:
        print(
            f"FOREBET_MARKET_JINA label={label} status={r.status_code} "
            f"html_bytes={len(r.text)} fresh=1"
        )
        return None
    soup = BeautifulSoup(r.text, "lxml")
    plain = soup.get_text("\n", strip=True)
    rcnt = len(soup.select(".rcnt"))
    print(
        f"FOREBET_MARKET_JINA label={label} status={r.status_code} "
        f"html_bytes={len(r.text)} text_bytes={len(plain)} rcnt={rcnt} fresh=1"
    )
    if len(plain) < MIN_PAGE_TEXT:
        print(f"WARN Forebet {label} render too small text_bytes={len(plain)}")
        return None
    return plain


def lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]


def find_fixture_index(page_lines: list[str], home: str, away: str) -> int:
    """Find a fixture even when HTML flattening puts home/away on separate lines."""
    h, a = norm(home), norm(away)
    if not h or not a:
        return -1
    for i in range(len(page_lines)):
        for width in (1, 2, 3, 4):
            if i + width > len(page_lines):
                break
            n = norm(" ".join(page_lines[i : i + width]))
            if h in n and a in n:
                return i
    return -1


def _numbers(line: str) -> list[int]:
    values = []
    for token in re.findall(r"(?<!\d)(\d{1,3})%?(?!\d)", line):
        try:
            values.append(int(token))
        except ValueError:
            pass
    return values


def _pair_from_line(line: str) -> tuple[str, str] | None:
    nums = _numbers(line)
    for left, right in zip(nums, nums[1:]):
        if 0 <= left <= 100 and 0 <= right <= 100 and left + right == 100:
            return str(left), str(right)
    return None


def parse_row_window(page_lines: list[str], start: int) -> dict[str, str]:
    """Parse one Forebet list row from a tolerant text window.

    Forebet/Jina may render the two probabilities either on one line or as two
    adjacent text nodes, and may put `Under 5-4` on one line.  Requiring an exact
    `55 45` line was therefore too brittle.
    """
    if start < 0:
        return {}

    end = min(len(page_lines), start + 30)
    pair: tuple[str, str] | None = None
    pair_at = -1

    for i in range(start + 1, end):
        pair = _pair_from_line(page_lines[i])
        if pair:
            pair_at = i
            break
        # Probabilities are sometimes separate text nodes, e.g. `55` then `45`.
        if i + 1 < end:
            left = page_lines[i].strip().rstrip("%")
            right = page_lines[i + 1].strip().rstrip("%")
            if INTEGER_ONLY_RE.match(page_lines[i].strip()) and INTEGER_ONLY_RE.match(page_lines[i + 1].strip()):
                try:
                    li, ri = int(left), int(right)
                except ValueError:
                    continue
                if 0 <= li <= 100 and 0 <= ri <= 100 and li + ri == 100:
                    pair = (str(li), str(ri))
                    pair_at = i
                    break

    if not pair:
        return {}

    pred = ""
    score = ""
    avg = ""
    score_at = -1
    for i in range(pair_at, end):
        line = page_lines[i]
        m_pred = re.search(r"\b(under|over)\b", line, flags=re.I)
        if m_pred and not pred:
            pred = m_pred.group(1).capitalize()
            m_score = SCORE_SEARCH_RE.search(line[m_pred.end() :])
            if m_score:
                score = text_score(m_score.group(1), m_score.group(2))
                score_at = i
            continue
        if pred and not score:
            m_score = SCORE_SEARCH_RE.search(line)
            if m_score:
                score = text_score(m_score.group(1), m_score.group(2))
                score_at = i
                continue
        if score:
            # Avg goals/corners is normally the first decimal after predicted score.
            m_avg = DECIMAL_SEARCH_RE.search(line if i > score_at else "")
            if m_avg:
                avg = m_avg.group(1)
                break

    if not pred:
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
        corner_url = f"https://www.forebet.com/en/football-predictions/corners/{d}/by-league"
        ou_text = fetch_page_text(ou_url, f"ou25_{d}")
        calls += 1
        corner_text = fetch_page_text(corner_url, f"corners95_{d}")
        calls += 1
        ou_pages[d] = lines(ou_text or "")
        corner_pages[d] = lines(corner_text or "")

    ou_count = corner_count = corner_listed = 0
    corner_parse_failures: list[str] = []
    corner_unlisted: list[str] = []
    for row in rows:
        d = (row.get("match_date") or "").strip()
        home = row.get("home_team", "")
        away = row.get("away_team", "")

        ou_idx = find_fixture_index(ou_pages.get(d, []), home, away)
        ou = parse_row_window(ou_pages.get(d, []), ou_idx)
        if ou:
            row["prediction_ou25"] = ou["prediction"]
            row["prob_over25"] = ou["over"]
            row["prob_under25"] = ou["under"]
            row["ou_predicted_score"] = ou["score"]
            if not row.get("avg_goals") and ou.get("avg"):
                row["avg_goals"] = ou["avg"]
            ou_count += 1

        c_idx = find_fixture_index(corner_pages.get(d, []), home, away)
        if c_idx >= 0:
            corner_listed += 1
            corners = parse_row_window(corner_pages.get(d, []), c_idx)
            if corners:
                row["corner_prediction"] = corners["prediction"]
                row["corner_prob_under95"] = corners["under"]
                row["corner_prob_over95"] = corners["over"]
                row["corner_predicted_score"] = corners["score"]
                row["avg_corners"] = corners["avg"]
                corner_count += 1
            else:
                corner_parse_failures.append(
                    f"{row.get('hkjc_event_id','')}:{home} vs {away}"
                )
        else:
            corner_unlisted.append(f"{row.get('hkjc_event_id','')}:{home} vs {away}")

    tmp = FEED.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(FEED)

    print(
        f"FOREBET_MARKETS_BATCH rows={len(rows)} dates={len(dates)} "
        f"ou25={ou_count} corner_listed={corner_listed} corners95={corner_count} "
        f"corner_unlisted={len(corner_unlisted)} corner_parse_failures={len(corner_parse_failures)} "
        f"jina_calls={calls} scraperapi_credits=0"
    )
    if corner_unlisted:
        print("FOREBET_CORNER_UNLISTED " + " | ".join(corner_unlisted[:20]))
    if corner_parse_failures:
        print("FOREBET_CORNER_PARSE_FAILURES " + " | ".join(corner_parse_failures[:20]))
        raise SystemExit(
            f"Forebet corner fixtures listed but not parsed: {len(corner_parse_failures)}"
        )
    if ou_count == 0:
        raise SystemExit("zero Forebet O/U rows parsed")
    if corner_count == 0:
        raise SystemExit("zero Forebet corner rows parsed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
