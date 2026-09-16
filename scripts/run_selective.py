"""Production entrypoint for the HKJC-gated Forebet feed.

Architecture:
- HKJC GraphQL defines the current bettable fixture universe.
- A persistent Forebet -> HKJC team-alias registry is loaded before matching.
- Forebet pages are generic source pages; no league-specific routing is allowed.
- ScraperAPI is retained only as a bounded transport fallback while the free
  rendered-source path is being validated.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import scrape_forebet as feed

DIRECT_TARGETS = Path("data/hkjc_targets.csv")
ALIAS_REGISTRY = Path("data/team_alias_registry.csv")
DIRECT_MAX_AGE_MINUTES = 180
feed.MAX_COST = "10"

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


def _forebet_date_from_hkt(kickoff_hkt: str, fallback: str) -> str:
    """Translate HKT kickoff to the calendar date used by Forebet pages."""
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


def _requested_page_date(_value: str, fallback: str) -> str:
    return fallback


feed.normalize_date = _requested_page_date


def _load_alias_registry() -> int:
    """Load persistent aliases into the normalizer before any fixture matching."""
    if not ALIAS_REGISTRY.exists():
        print("FOREBET_ALIAS_REGISTRY rows=0 status=missing", flush=True)
        return 0

    loaded = 0
    conflicts = 0
    with ALIAS_REGISTRY.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            status = (row.get("status") or "").strip().upper()
            if status == "CONFLICT":
                conflicts += 1
                continue
            alias = (row.get("forebet_alias") or "").strip()
            canonical = (row.get("canonical_hkjc_name") or "").strip()
            if not alias or not canonical:
                continue
            # Resolve using the base normalizer before inserting the new alias.
            alias_key = feed.normalize_team(alias)
            canonical_value = feed.normalize_team(canonical)
            if alias_key and canonical_value:
                feed.ALIASES[alias_key] = canonical_value
                loaded += 1

    print(
        f"FOREBET_ALIAS_REGISTRY rows={loaded} conflicts_skipped={conflicts}",
        flush=True,
    )
    return loaded


_load_alias_registry()


def _translate_target_dates(rows):
    translated = []
    for row in rows:
        item = dict(row)
        item["match_date"] = _forebet_date_from_hkt(
            item.get("kickoff_hkt", ""), item.get("match_date", "")
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
    return _translate_target_dates(_legacy_load_targets())


feed.load_hkjc_targets = _load_direct_or_fallback


def _fetch_forebet_generic_date(match_date: str):
    """Generic dated Forebet transport. No league-specific supplemental routes."""
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
        print(f"ERROR: Forebet request failed for {match_date}: {exc}", file=feed.sys.stderr)
        return None, None

    raw_cost = r.headers.get("sa-credit-cost")
    try:
        cost = int(float(raw_cost)) if raw_cost else None
    except ValueError:
        cost = None
    print(
        f"FOREBET_GENERIC_DATE date={match_date} status={r.status_code} "
        f"credit_cost={raw_cost or 'unknown'} bytes={len(r.text)}",
        flush=True,
    )
    if r.status_code != 200 or "rcnt" not in r.text:
        return None, cost
    return r.text, cost


feed.fetch_forebet_date = _fetch_forebet_generic_date


def _attach_only_usable(row, targets):
    probs = (row.get("prob_home"), row.get("prob_draw"), row.get("prob_away"))
    if not all(isinstance(v, (int, float)) for v in probs):
        return None
    return _original_attach(row, targets)


feed.attach_hkjc_target = _attach_only_usable

if __name__ == "__main__":
    raise SystemExit(feed.main())
