"""Production entrypoint for the HKJC-gated Forebet feed.

Primary gate: freshly captured HKJC GraphQL HAD fixtures in data/hkjc_targets.csv.
Fallback gate: the legacy Google Sheet HKJC Source Snapshot only when the direct
file is absent, stale or invalid.  Only keep HKJC-bettable fixtures with a usable
Forebet 1X2 probability triplet.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import scrape_forebet as feed

DIRECT_TARGETS = Path("data/hkjc_targets.csv")
DIRECT_MAX_AGE_MINUTES = 180

# The successful Forebet request cost 10 credits. Refuse any request that would
# cost more instead of silently burning the free ScraperAPI allowance.
feed.MAX_COST = "10"

# Forebet can encode early-HKT fixtures with the previous calendar date. The
# page itself was chosen from the HKJC HKT target date, so use that page date
# for pair matching instead of spending a second ScraperAPI request.
def _requested_page_date(_value: str, fallback: str) -> str:
    return fallback


feed.normalize_date = _requested_page_date

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
                    print(
                        f"HKJC_GATE_SOURCE direct_graphql rows={len(usable)} "
                        f"age_min={age:.1f}",
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
    return _legacy_load_targets()


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
