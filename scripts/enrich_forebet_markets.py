"""Batch-enrich HKJC-matched Forebet rows with O/U 2.5 and corners 9.5.

Durable routine:
- zero ScraperAPI credits;
- cheap fresh Jina Markdown first;
- retry a date with browser rendering only when corner coverage is weak;
- use both Forebet match_date and HKJC kickoff date for midnight-crossing fixtures;
- exact Forebet home/away names from the already-matched 1X2 feed are the join key;
- tolerate teams/probabilities split across rendered text nodes;
- preserve archived secondary-market values elsewhere in the pipeline;
- fail on obvious fresh-source incompleteness instead of silently accepting it.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "forebet_current.csv"
JINA = "https://r.jina.ai/"
TIMEOUT = 70
MIN_PAGE_TEXT = 500
MIN_FRESH_CORNER_RATIO = 0.50
MIN_DATE_ROWS_FOR_GATE = 5
MIN_DATE_CORNER_RATIO = 0.35

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
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def text_score(home: str, away: str) -> str:
    return f"{home} - {away}"


def lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]


def read_feed() -> tuple[list[dict[str, str]], list[str]]:
    with FEED.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def _iso_date_from_value(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 10 and ISO_DATE_RE.match(value[:10]):
        return value[:10]
    for fmt in ("%m/%d/%Y %I:%M %p", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def candidate_dates(row: dict[str, str]) -> list[str]:
    """Try Forebet's stored date plus HKJC local kickoff date."""
    out: list[str] = []
    for value in (
        row.get("match_date", ""),
        row.get("hkjc_kickoff_hkt", ""),
        row.get("kickoff_text", ""),
    ):
        d = _iso_date_from_value(value)
        if d and d not in out:
            out.append(d)
    return out


def fetch_jina(url: str, label: str, mode: str = "cheap") -> str | None:
    if mode == "browser":
        headers = {
            "X-Engine": "browser",
            "X-Return-Format": "markdown",
            "X-Respond-Timing": "mutation-idle",
            "X-Timeout": "30",
            "User-Agent": "Mozilla/5.0",
            "X-Cache-Tolerance": "0",
        }
        timeout = TIMEOUT
    else:
        headers = {
            "X-Timeout": "30",
            "User-Agent": "Mozilla/5.0",
            "X-No-Cache": "true",
            "X-Cache-Tolerance": "0",
        }
        timeout = 50

    try:
        response = requests.get(JINA + url, headers=headers, timeout=timeout)
    except Exception as exc:
        print(f"WARN Jina {label} mode={mode} failed: {exc}")
        return None

    print(
        f"FOREBET_MARKET_JINA label={label} mode={mode} "
        f"status={response.status_code} bytes={len(response.text)}"
    )
    if response.status_code != 200 or len(response.text) < MIN_PAGE_TEXT:
        return None
    return response.text


def find_fixture_index(page_lines: list[str], home: str, away: str) -> int:
    h, a = norm(home), norm(away)
    if not h or not a:
        return -1
    for i in range(len(page_lines)):
        for width in (1, 2, 3, 4):
            if i + width > len(page_lines):
                break
            joined = norm(" ".join(page_lines[i : i + width]))
            if h in joined and a in joined:
                return i
    return -1


def _numbers(line: str) -> list[int]:
    values: list[int] = []
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

        if i + 1 < end:
            left_raw = page_lines[i].strip()
            right_raw = page_lines[i + 1].strip()
            if INTEGER_ONLY_RE.match(left_raw) and INTEGER_ONLY_RE.match(right_raw):
                try:
                    left = int(left_raw.rstrip("%"))
                    right = int(right_raw.rstrip("%"))
                except ValueError:
                    continue
                if 0 <= left <= 100 and 0 <= right <= 100 and left + right == 100:
                    pair = (str(left), str(right))
                    pair_at = i
                    break

    if not pair:
        return {}

    prediction = ""
    score = ""
    avg = ""
    score_at = -1

    for i in range(pair_at, end):
        line = page_lines[i]
        m_pred = re.search(r"\b(under|over)\b", line, flags=re.I)
        if m_pred and not prediction:
            prediction = m_pred.group(1).capitalize()
            m_score = SCORE_SEARCH_RE.search(line[m_pred.end() :])
            if m_score:
                score = text_score(m_score.group(1), m_score.group(2))
                score_at = i
            continue

        if prediction and not score:
            m_score = SCORE_SEARCH_RE.search(line)
            if m_score:
                score = text_score(m_score.group(1), m_score.group(2))
                score_at = i
                continue

        if score:
            m_avg = DECIMAL_SEARCH_RE.search(line if i > score_at else "")
            if m_avg:
                avg = m_avg.group(1)
                break

    if not prediction:
        return {}

    return {
        "under": pair[0],
        "over": pair[1],
        "prediction": prediction,
        "score": score,
        "avg": avg,
    }


def parse_for_row(page_lines: list[str], row: dict[str, str]) -> dict[str, str]:
    idx = find_fixture_index(
        page_lines,
        row.get("home_team", ""),
        row.get("away_team", ""),
    )
    return parse_row_window(page_lines, idx)


def page_fixture_coverage(page_lines: list[str], rows: list[dict[str, str]]) -> tuple[int, int]:
    listed = parsed = 0
    for row in rows:
        idx = find_fixture_index(
            page_lines,
            row.get("home_team", ""),
            row.get("away_team", ""),
        )
        if idx >= 0:
            listed += 1
            if parse_row_window(page_lines, idx):
                parsed += 1
    return listed, parsed


def debug_unparsed_windows(
    page_lines: list[str],
    rows: list[dict[str, str]],
    date: str,
    limit: int = 3,
) -> None:
    """Print small raw windows for listed fixtures the parser cannot decode."""
    shown = 0
    for row in rows:
        idx = find_fixture_index(
            page_lines,
            row.get("home_team", ""),
            row.get("away_team", ""),
        )
        if idx < 0 or parse_row_window(page_lines, idx):
            continue
        event_id = row.get("hkjc_event_id", "")
        print(
            f"FOREBET_CORNER_DEBUG_BEGIN date={date} event={event_id} "
            f"fixture={row.get('home_team','')} vs {row.get('away_team','')} idx={idx}"
        )
        lo = max(0, idx - 8)
        hi = min(len(page_lines), idx + 24)
        for line_no in range(lo, hi):
            marker = ">>" if line_no == idx else "  "
            print(f"FOREBET_CORNER_DEBUG {marker} {line_no}: {page_lines[line_no]!r}")
        print(f"FOREBET_CORNER_DEBUG_END date={date} event={event_id}")
        shown += 1
        if shown >= limit:
            break


def fetch_market_pages(
    market: str,
    dates: list[str],
    primary_rows_by_date: dict[str, list[dict[str, str]]],
) -> tuple[dict[str, list[str]], int]:
    pages: dict[str, list[str]] = {}
    calls = 0

    for date in dates:
        if market == "ou25":
            url = (
                "https://www.forebet.com/en/football-predictions/"
                f"under-over-25-goals/{date}/by-league"
            )
        else:
            url = (
                "https://www.forebet.com/en/football-predictions/"
                f"corners/{date}/by-league"
            )

        cheap = fetch_jina(url, f"{market}_{date}", "cheap")
        calls += 1
        chosen = lines(cheap or "")

        if market == "corners":
            date_rows = primary_rows_by_date.get(date, [])
            listed, parsed = page_fixture_coverage(chosen, date_rows)
            ratio = parsed / len(date_rows) if date_rows else 1.0
            print(
                f"FOREBET_CORNER_DATE_CHEAP date={date} rows={len(date_rows)} "
                f"listed={listed} parsed={parsed} ratio={ratio:.1%}"
            )
            if listed and parsed < listed:
                debug_unparsed_windows(chosen, date_rows, date)

            if date_rows and ratio < 0.60:
                browser = fetch_jina(url, f"{market}_{date}", "browser")
                calls += 1
                browser_lines = lines(browser or "")
                b_listed, b_parsed = page_fixture_coverage(browser_lines, date_rows)
                print(
                    f"FOREBET_CORNER_DATE_BROWSER date={date} rows={len(date_rows)} "
                    f"listed={b_listed} parsed={b_parsed} "
                    f"ratio={(b_parsed / len(date_rows)):.1%}"
                )
                if b_parsed > parsed or (b_parsed == parsed and b_listed > listed):
                    chosen = browser_lines

        pages[date] = chosen

    return pages, calls


def lookup_row(
    row: dict[str, str],
    pages: dict[str, list[str]],
) -> tuple[dict[str, str], str, bool]:
    listed_any = False
    for date in candidate_dates(row):
        page_lines = pages.get(date, [])
        idx = find_fixture_index(
            page_lines,
            row.get("home_team", ""),
            row.get("away_team", ""),
        )
        if idx < 0:
            continue
        listed_any = True
        parsed = parse_row_window(page_lines, idx)
        if parsed:
            return parsed, date, True
    return {}, "", listed_any


def main() -> int:
    if not FEED.exists():
        raise SystemExit(f"missing {FEED}")

    rows, fields = read_feed()
    if not rows:
        raise SystemExit("zero Forebet rows to enrich")

    for field in EXTRA_FIELDS:
        if field not in fields:
            fields.append(field)

    primary_rows_by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    all_dates: set[str] = set()
    for row in rows:
        candidates = candidate_dates(row)
        if not candidates:
            continue
        primary_rows_by_date[candidates[0]].append(row)
        all_dates.update(candidates)

    dates = sorted(all_dates)
    ou_pages, ou_calls = fetch_market_pages("ou25", dates, primary_rows_by_date)
    corner_pages, corner_calls = fetch_market_pages("corners", dates, primary_rows_by_date)

    ou_count = 0
    corner_count = 0
    corner_listed = 0
    corner_parse_failures: list[str] = []
    corner_unlisted: list[str] = []
    fresh_corner_by_primary_date: dict[str, int] = defaultdict(int)

    for row in rows:
        ou, _, _ = lookup_row(row, ou_pages)
        if ou:
            row["prediction_ou25"] = ou["prediction"]
            row["prob_over25"] = ou["over"]
            row["prob_under25"] = ou["under"]
            row["ou_predicted_score"] = ou["score"]
            if not row.get("avg_goals") and ou.get("avg"):
                row["avg_goals"] = ou["avg"]
            ou_count += 1

        corners, used_date, listed = lookup_row(row, corner_pages)
        if listed:
            corner_listed += 1
        if corners:
            row["corner_prediction"] = corners["prediction"]
            row["corner_prob_under95"] = corners["under"]
            row["corner_prob_over95"] = corners["over"]
            row["corner_predicted_score"] = corners["score"]
            row["avg_corners"] = corners["avg"]
            corner_count += 1
            primary = candidate_dates(row)[0] if candidate_dates(row) else used_date
            if primary:
                fresh_corner_by_primary_date[primary] += 1
        elif listed:
            corner_parse_failures.append(
                f"{row.get('hkjc_event_id','')}:{row.get('home_team','')} "
                f"vs {row.get('away_team','')}"
            )
        else:
            corner_unlisted.append(
                f"{row.get('hkjc_event_id','')}:{row.get('home_team','')} "
                f"vs {row.get('away_team','')}"
            )

    tmp = FEED.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(FEED)

    fresh_corner_ratio = corner_count / len(rows)
    print(
        f"FOREBET_MARKETS_BATCH rows={len(rows)} dates={len(dates)} "
        f"ou25={ou_count} corner_listed={corner_listed} corners95={corner_count} "
        f"fresh_corner_ratio={fresh_corner_ratio:.1%} "
        f"corner_unlisted={len(corner_unlisted)} "
        f"corner_parse_failures={len(corner_parse_failures)} "
        f"jina_calls={ou_calls + corner_calls} scraperapi_credits=0"
    )

    for date, date_rows in sorted(primary_rows_by_date.items()):
        parsed = fresh_corner_by_primary_date.get(date, 0)
        ratio = parsed / len(date_rows) if date_rows else 1.0
        print(
            f"FOREBET_CORNER_DATE_FINAL date={date} rows={len(date_rows)} "
            f"parsed={parsed} ratio={ratio:.1%}"
        )
        if len(date_rows) >= MIN_DATE_ROWS_FOR_GATE and ratio < MIN_DATE_CORNER_RATIO:
            raise SystemExit(
                f"Forebet corner date coverage too low: "
                f"{date} {parsed}/{len(date_rows)} ({ratio:.1%})"
            )

    if corner_unlisted:
        print("FOREBET_CORNER_UNLISTED " + " | ".join(corner_unlisted[:20]))

    if corner_parse_failures:
        print(
            "FOREBET_CORNER_PARSE_FAILURES "
            + " | ".join(corner_parse_failures[:20])
        )
        raise SystemExit(
            f"Forebet corner fixtures listed but not parsed: "
            f"{len(corner_parse_failures)}"
        )

    if ou_count == 0:
        raise SystemExit("zero Forebet O/U rows parsed")
    if corner_count == 0:
        raise SystemExit("zero Forebet corner rows parsed")
    if fresh_corner_ratio < MIN_FRESH_CORNER_RATIO:
        raise SystemExit(
            f"Forebet fresh corner coverage too low: "
            f"{corner_count}/{len(rows)} ({fresh_corner_ratio:.1%})"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
