"""Production entrypoint for the HKJC-gated Forebet feed.

Durable architecture:
- HKJC GraphQL defines the bettable fixture universe.
- Persistent Forebet -> HKJC aliases are loaded before matching.
- Forebet is fetched through generic Jina-rendered public pages only.
- No league-specific routes and no ScraperAPI calls are used in routine production.
- The existing rolling archive preserves the last model for an event if a later
  public-page refresh temporarily omits it.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import scrape_forebet as feed

DIRECT_TARGETS = Path("data/hkjc_targets.csv")
ALIAS_REGISTRY = Path("data/team_alias_registry.csv")
DIRECT_MAX_AGE_MINUTES = 180
JINA_PREFIX = "https://r.jina.ai/"
JINA_TIMEOUT = 90

_legacy_load_targets = feed.load_hkjc_targets
_original_attach = feed.attach_hkjc_target
_GLOBAL_HTML_CACHE: str | None = None


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


def _row_date(value: str, fallback: str) -> str:
    """Use Forebet row datetime when present; otherwise use the requested page date."""
    value = (value or "").strip()
    m = re.search(r"(\d{4}-\d{2}-\d{2})", value)
    return m.group(1) if m else fallback


feed.normalize_date = _row_date


def _load_alias_registry() -> int:
    if not ALIAS_REGISTRY.exists():
        print("FOREBET_ALIAS_REGISTRY rows=0 status=missing", flush=True)
        return 0
    loaded = conflicts = 0
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
            alias_key = feed.normalize_team(alias)
            canonical_value = feed.normalize_team(canonical)
            if alias_key and canonical_value:
                feed.ALIASES[alias_key] = canonical_value
                loaded += 1
    print(f"FOREBET_ALIAS_REGISTRY rows={loaded} conflicts_skipped={conflicts}", flush=True)
    return loaded


_load_alias_registry()


def _translate_target_dates(rows):
    out = []
    for row in rows:
        item = dict(row)
        item["match_date"] = _forebet_date_from_hkt(
            item.get("kickoff_hkt", ""), item.get("match_date", "")
        )
        out.append(item)
    return out


def _load_direct_or_fallback():
    if DIRECT_TARGETS.exists():
        try:
            with DIRECT_TARGETS.open(encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            usable = [
                r for r in rows
                if r.get("hkjc_event_id") and r.get("match_date")
                and r.get("home_en") and r.get("away_en")
                and all(r.get(k) for k in ("had_home", "had_draw", "had_away"))
            ]
            stamps = [_parse_iso(r.get("fetched_at_hkt", "")) for r in usable]
            stamps = [x for x in stamps if x is not None]
            if usable and stamps:
                age = (datetime.now(timezone.utc) - max(stamps)).total_seconds() / 60
                if -10 <= age <= DIRECT_MAX_AGE_MINUTES:
                    usable = _translate_target_dates(usable)
                    print(
                        f"HKJC_GATE_SOURCE direct_graphql rows={len(usable)} age_min={age:.1f} "
                        f"forebet_dates={','.join(sorted({r['match_date'] for r in usable}))}",
                        flush=True,
                    )
                    return usable
                print(f"WARN: direct HKJC targets stale age_min={age:.1f}; using snapshot fallback", flush=True)
        except Exception as exc:
            print(f"WARN: direct HKJC targets invalid ({exc}); using snapshot fallback", flush=True)
    print("HKJC_GATE_SOURCE legacy_google_snapshot_fallback", flush=True)
    return _translate_target_dates(_legacy_load_targets())


feed.load_hkjc_targets = _load_direct_or_fallback


def _jina_html(url: str, label: str) -> str | None:
    try:
        r = feed.requests.get(
            JINA_PREFIX + url,
            headers={"x-respond-with": "html", "x-timeout": "30", "User-Agent": "Mozilla/5.0"},
            timeout=JINA_TIMEOUT,
        )
    except Exception as exc:
        print(f"ERROR: Jina Forebet {label} failed: {exc}", file=feed.sys.stderr)
        return None
    print(f"FOREBET_JINA label={label} status={r.status_code} bytes={len(r.text)}", flush=True)
    if r.status_code != 200 or "rcnt" not in r.text:
        return None
    return r.text


def _global_forebet_html() -> str:
    global _GLOBAL_HTML_CACHE
    if _GLOBAL_HTML_CACHE is not None:
        return _GLOBAL_HTML_CACHE
    # These are generic all-predictions views, not league-specific exceptions.
    urls = [
        "https://www.forebet.com/en/football-predictions/predictions-1x2?start=2",
        "https://www.forebet.com/en/football-predictions?start=1",
    ]
    parts: list[str] = []
    for i, url in enumerate(urls, 1):
        html = _jina_html(url, f"global_{i}")
        if html:
            parts.append(html)
    _GLOBAL_HTML_CACHE = "\n".join(parts)
    return _GLOBAL_HTML_CACHE


def _fetch_forebet_generic_date(match_date: str):
    """Combine the dated page with generic all-predictions pages; zero paid credits."""
    parts: list[str] = []
    dated_url = (
        "https://www.forebet.com/en/football-predictions/"
        f"predictions-1x2/{match_date}/by-league"
    )
    dated = _jina_html(dated_url, f"date_{match_date}")
    if dated:
        parts.append(dated)
    global_html = _global_forebet_html()
    if global_html:
        parts.append(global_html)
    if not parts:
        print(f"ERROR: zero free Forebet source pages for {match_date}", file=feed.sys.stderr)
        return None, 0
    return "\n".join(parts), 0


feed.fetch_forebet_date = _fetch_forebet_generic_date


def _attach_only_usable(row, targets):
    probs = (row.get("prob_home"), row.get("prob_draw"), row.get("prob_away"))
    if not all(isinstance(v, (int, float)) for v in probs):
        return None
    return _original_attach(row, targets)


feed.attach_hkjc_target = _attach_only_usable

if __name__ == "__main__":
    raise SystemExit(feed.main())
