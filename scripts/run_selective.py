"""Production entrypoint for the HKJC-gated Forebet feed.

Primary gate: freshly captured HKJC GraphQL HAD fixtures in data/hkjc_targets.csv.
Fallback gate: the legacy Google Sheet HKJC Source Snapshot only when the direct
file is absent, stale or invalid. Only keep HKJC-bettable fixtures with a usable
Forebet 1X2 probability triplet.

Forebet dates are GMT-facing, while HKJC kickoff dates are HKT. We therefore
translate the in-memory target match_date from HKT to GMT before selecting the
Forebet date page. The /by-league route is used because it contains the complete
day rather than only the first time-sorted page.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import scrape_forebet as feed

DIRECT_TARGETS = Path("data/hkjc_targets.csv")
DIRECT_MAX_AGE_MINUTES = 180

# The successful Forebet request costs 10 credits. Refuse any request that would
# cost more instead of silently burning the free ScraperAPI allowance.
feed.MAX_COST = "10"

# Known source-name differences that are safe to collapse before fuzzy matching.
feed.ALIASES.update({
    "al wahda": "wahda abu dhabi",
    "al wahda abu dhabi": "wahda abu dhabi",
    "wahda abu dhabi": "wahda abu dhabi",
})


def _forebet_date_from_hkt(kickoff_hkt: str, fallback: str) -> str:
    """Return the Forebet/GMT calendar date for an HKJC HKT kickoff."""
    value = (kickoff_hkt or "").strip()
    if not value:
        return fallback
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return fallback
    return (dt - timedelta(hours=8)).date().isoformat()


# parse_forebet_rows receives a Forebet/GMT page date. Keep that page date as
# the row key; direct targets below are translated to the same date basis.
def _requested_page_date(_value: str, fallback: str) -> str:
    return fallback


feed.normalize_date = _requested_page_date


def _fetch_forebet_complete_date(match_date: str):
    """Fetch the complete Forebet date view in one paid request."""
    if not feed.SCRAPERAPI_KEY:
        print("FATAL: missing SCRAPERAPI_KEY GitHub Actions secret", file=feed.sys.stderr)
        return None, None

    url = (
        "https://www.forebet.com/en/football-predictions/"
        f"predictions-1x2/{match_date}/by-league"
    )
    params = {
        "api_key": feed.SCRAPERAPI_KEY,
        "url": url,
        "max_cost": feed.MAX_COST,
    }
    try:
        r = feed.requests.get(feed.SCRAPERAPI_URL, params=params, timeout=70)
    except Exception as exc:
        print(
            f"ERROR: ScraperAPI complete-date request failed for {match_date}: {exc}",
            file=feed.sys.stderr,
        )
        return None, None

    raw_cost = r.headers.get("sa-credit-cost")
    try:
        credit_cost = int(float(raw_cost)) if raw_cost else None
    except ValueError:
        credit_cost = None

    print(
        f"SCRAPERAPI_COMPLETE_DATE date={match_date} status={r.status_code} "
        f"credit_cost={raw_cost or 'unknown'} bytes={len(r.text)}",
        flush=True,
    )
    if r.status_code != 200:
        print(
            f"ERROR: ScraperAPI non-200 for {match_date}; no retry",
            file=feed.sys.stderr,
        )
        return None, credit_cost
    if "rcnt" not in r.text:
        print(
            f"ERROR: Forebet complete-date rows missing for {match_date}; no retry",
            file=feed.sys.stderr,
        )
        return None, credit_cost
    return r.text, credit_cost


feed.fetch_forebet_date = _fetch_forebet_complete_date

_legacy_load_targets = feed.load_hkjc_targets


def _parse_iso(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _translate_target_dates(rows):
    translated = []
    for row in rows:
        item = dict(row)
        item["match_date"] = _forebet_date_from_hkt(
            item.get("kickoff_hkt", ""),
            item.get("match_date", ""),
        )
        translated.append(item)
    return translated


def _load_direct_or_fallback():
    if DIRECT_TARGETS.exists():
        try:
            with DIRECT_TARGETS.open(encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            usable = [
                r for r in rows
                if r.get("hkjc_event_id")
                and r.get("match_date")
                and r.get("home_en")
                and r.get("away_en")
                and all(r.get(k) for k in ("had_home", "had_draw", "had_away"))
            ]
            stamps = [_parse_iso(r.get("fetched_at_hkt", "")) for r in usable]
            stamps = [x for x in stamps if x is not None]
            if usable and stamps:
                latest = max(stamps)
                age = (datetime.now(timezone.utc) - latest).total_seconds() / 60
                if -10 <= age <= DIRECT_MAX_AGE_MINUTES:
                    usable = _translate_target_dates(usable)
                    print(
                        f"HKJC_GATE_SOURCE direct_graphql rows={len(usable)} "
                        f"age_min={age:.1f} forebet_dates="
                        f"{','.join(sorted({r['match_date'] for r in usable}))}",
                        flush=True,
                    )
                    return usable
                print(
                    f"WARN: direct HKJC target file stale age_min={age:.1f}; "
                    "using legacy snapshot fallback",
                    flush=True,
                )
        except Exception as exc:
            print(f"WARN: direct HKJC targets invalid ({exc}); using fallback", flush=True)

    print("HKJC_GATE_SOURCE legacy_google_snapshot_fallback", flush=True)
    legacy = _legacy_load_targets()
    return _translate_target_dates(legacy)


feed.load_hkjc_targets = _load_direct_or_fallback

# A match is not useful to Fast Tracker without all three 1X2 model
# probabilities. Filter it before it can be written to the production CSV.
_original_attach = feed.attach_hkjc_target


def _attach_only_usable(row, targets):
    probs = (row.get("prob_home"), row.get("prob_draw"), row.get("prob_away"))
    if not all(isinstance(v, (int, float)) for v in probs):
        return None
    return _original_attach(row, targets)


feed.attach_hkjc_target = _attach_only_usable

if __name__ == "__main__":
    raise SystemExit(feed.main())
