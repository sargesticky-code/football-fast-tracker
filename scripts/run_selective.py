"""Production entrypoint for the HKJC-gated Forebet feed.

Primary gate: freshly captured HKJC GraphQL HAD fixtures in data/hkjc_targets.csv.
Fallback gate: the legacy Google Sheet HKJC Source Snapshot only when the direct
file is absent, stale or invalid. Only keep HKJC-bettable fixtures with a usable
Forebet 1X2 probability triplet.

Forebet date pages do not always expose every league in their first HTML payload.
Production therefore uses the /by-league date view first, then conditionally fetches
small league-specific supplements only when HKJC has targets in that league that
were not found in the main page. This keeps paid ScraperAPI usage bounded while
avoiding silent coverage gaps.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import scrape_forebet as feed

DIRECT_TARGETS = Path("data/hkjc_targets.csv")
DIRECT_MAX_AGE_MINUTES = 180

# The successful Forebet request costs 10 credits. Refuse any single request that
# would cost more instead of silently burning the free ScraperAPI allowance.
feed.MAX_COST = "10"

# Populated when the HKJC gate is loaded. The fetch layer uses this only to decide
# whether a supplemental league page is actually necessary.
_ACTIVE_TARGETS: list[dict] = []

# League-specific Forebet pages that are known to expose fixtures omitted from the
# first daily HTML payload. Add routes here only after an isolated probe succeeds.
SUPPLEMENTAL_LEAGUE_ROUTES = {
    "AC2": "https://www.forebet.com/en/predictions-asia/afc-cup",
}

# Known source-name differences that are safe to collapse before fuzzy matching.
feed.ALIASES.update({
    "al wahda": "wahda abu dhabi",
    "al wahda abu dhabi": "wahda abu dhabi",
    "wahda abu dhabi": "wahda abu dhabi",
})


def _forebet_date_from_hkt(kickoff_hkt: str, fallback: str) -> str:
    """Return the Forebet-facing calendar date for an HKJC HKT kickoff."""
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
    # Forebet's match pages expose the relevant fixtures on the preceding date for
    # early-HKT kickoffs. Subtracting eight hours gives the stable page key used by
    # this feed and fixes 00:00 HKT fixtures being requested from the wrong page.
    return (dt - timedelta(hours=8)).date().isoformat()


# parse_forebet_rows receives a Forebet page date. Keep that page date as the row
# key so it aligns with the translated HKJC targets above.
def _requested_page_date(_value: str, fallback: str) -> str:
    return fallback


feed.normalize_date = _requested_page_date

_legacy_load_targets = feed.load_hkjc_targets
_original_attach = feed.attach_hkjc_target


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


def _remember_targets(rows):
    global _ACTIVE_TARGETS
    _ACTIVE_TARGETS = list(rows)
    return rows


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
                    return _remember_targets(usable)
                print(
                    f"WARN: direct HKJC target file stale age_min={age:.1f}; "
                    "using legacy snapshot fallback",
                    flush=True,
                )
        except Exception as exc:
            print(f"WARN: direct HKJC targets invalid ({exc}); using fallback", flush=True)

    print("HKJC_GATE_SOURCE legacy_google_snapshot_fallback", flush=True)
    legacy = _translate_target_dates(_legacy_load_targets())
    return _remember_targets(legacy)


feed.load_hkjc_targets = _load_direct_or_fallback


def _paid_fetch(url: str, label: str):
    if not feed.SCRAPERAPI_KEY:
        print("FATAL: missing SCRAPERAPI_KEY GitHub Actions secret", file=feed.sys.stderr)
        return None, None
    params = {
        "api_key": feed.SCRAPERAPI_KEY,
        "url": url,
        "max_cost": feed.MAX_COST,
    }
    try:
        r = feed.requests.get(feed.SCRAPERAPI_URL, params=params, timeout=70)
    except Exception as exc:
        print(f"ERROR: ScraperAPI {label} request failed: {exc}", file=feed.sys.stderr)
        return None, None

    raw_cost = r.headers.get("sa-credit-cost")
    try:
        cost = int(float(raw_cost)) if raw_cost else None
    except ValueError:
        cost = None

    print(
        f"SCRAPERAPI_{label} status={r.status_code} "
        f"credit_cost={raw_cost or 'unknown'} bytes={len(r.text)} url={url}",
        flush=True,
    )
    if r.status_code != 200:
        return None, cost
    if "rcnt" not in r.text:
        print(f"ERROR: Forebet rows missing in {label}", file=feed.sys.stderr)
        return None, cost
    return r.text, cost


def _matched_target_ids(html: str, match_date: str, targets: list[dict]) -> set[str]:
    ids: set[str] = set()
    for row in feed.parse_forebet_rows(html, match_date):
        selected = _original_attach(row, targets)
        if selected is not None:
            ids.add(str(selected.get("hkjc_event_id") or ""))
    return ids


def _fetch_forebet_complete_date(match_date: str):
    """Fetch the daily view, then only the league supplements still required."""
    date_url = (
        "https://www.forebet.com/en/football-predictions/"
        f"predictions-1x2/{match_date}/by-league"
    )
    html, cost = _paid_fetch(date_url, f"DATE date={match_date}")
    if html is None:
        return None, cost

    total_cost = cost or 0
    parts = [html]
    date_targets = [t for t in _ACTIVE_TARGETS if t.get("match_date") == match_date]
    matched_ids = _matched_target_ids(html, match_date, date_targets)

    for league_key, league_url in SUPPLEMENTAL_LEAGUE_ROUTES.items():
        league_targets = [
            t for t in date_targets
            if (t.get("league_zh") or "").strip() in {league_key, "亞冠2"}
        ]
        if not league_targets:
            continue
        required_ids = {str(t.get("hkjc_event_id") or "") for t in league_targets}
        missing_ids = sorted(required_ids - matched_ids)
        if not missing_ids:
            print(
                f"FOREBET_SUPPLEMENT_SKIP league={league_key} date={match_date} reason=covered",
                flush=True,
            )
            continue

        print(
            f"FOREBET_SUPPLEMENT_NEEDED league={league_key} date={match_date} "
            f"missing={','.join(missing_ids)}",
            flush=True,
        )
        extra_html, extra_cost = _paid_fetch(
            league_url,
            f"SUPPLEMENT league={league_key} date={match_date}",
        )
        if extra_cost is not None:
            total_cost += extra_cost
        if extra_html is None:
            continue
        parts.append(extra_html)
        matched_ids |= _matched_target_ids(extra_html, match_date, league_targets)

    return "\n".join(parts), total_cost


feed.fetch_forebet_date = _fetch_forebet_complete_date


# A match is not useful to Fast Tracker without all three 1X2 model
# probabilities. Filter it before it can be written to the production CSV.
def _attach_only_usable(row, targets):
    probs = (row.get("prob_home"), row.get("prob_draw"), row.get("prob_away"))
    if not all(isinstance(v, (int, float)) for v in probs):
        return None
    return _original_attach(row, targets)


feed.attach_hkjc_target = _attach_only_usable

if __name__ == "__main__":
    raise SystemExit(feed.main())
