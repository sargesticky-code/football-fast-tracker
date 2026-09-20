"""Production entrypoint for the HKJC-gated Forebet feed.

Durable architecture:
- HKJC GraphQL defines the bettable fixture universe.
- Persistent Forebet -> HKJC aliases are loaded before matching.
- Forebet is fetched through generic Jina-rendered public pages only.
- No league-specific routes and no ScraperAPI calls are used in routine production.
- Jina pages are health-checked and retried with cache bypass if a 200 placeholder
  or otherwise empty render is returned.
- Generic all-predictions pagination is target-aware and bounded; it stops when the
  active HKJC targets for a date are covered or the generic page budget is exhausted.
- If a free-page refresh is partial, an already-known model for an HKJC event that
  is still active is carried forward rather than silently disappearing.
"""
from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import scrape_forebet as feed

DIRECT_TARGETS = Path("data/hkjc_targets.csv")
CURRENT_FEED = Path("data/forebet_current.csv")
ALIAS_REGISTRY = Path("data/team_alias_registry.csv")
MANUAL_ALIAS = Path("data/team_alias_manual.csv")
DIRECT_MAX_AGE_MINUTES = 180
JINA_PREFIX = "https://r.jina.ai/"
JINA_TIMEOUT = 90
MAX_GENERIC_PAGES = 5
MIN_HEALTHY_BYTES = 20_000

_legacy_load_targets = feed.load_hkjc_targets
_original_attach = feed.attach_hkjc_target
_ACTIVE_TARGETS: list[dict] = []
_JINA_CACHE: dict[str, str | None] = {}
_BROWSER_CACHE: dict[str, str | None] = {}
_JINA_CIRCUIT_OPEN = False
_BROWSER_CIRCUIT_OPEN = False
_PREVIOUS_CURRENT: list[dict[str, str]] = []


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
    value = (value or "").strip()
    m = re.search(r"(\d{4}-\d{2}-\d{2})", value)
    return m.group(1) if m else fallback


feed.normalize_date = _row_date


# Forebet's rendered <time datetime> can cross a UTC/HKT date boundary even
# when the fixture itself is the same HKJC event. Preserve strict same-date
# matching first; only recover an adjacent-date row when BOTH team names are
# exact after the production normalization policy and the candidate is unique.
_legacy_attach = _original_attach

def _attach_with_safe_date_rollover(row, targets):
    selected = _legacy_attach(row, targets)
    if selected is not None:
        return selected

    row_date_raw = str(row.get("match_date") or "").strip()
    try:
        row_date = datetime.fromisoformat(row_date_raw).date()
    except ValueError:
        return None

    candidates = []
    for target in targets:
        target_date_raw = str(target.get("match_date") or "").strip()
        try:
            target_date = datetime.fromisoformat(target_date_raw).date()
        except ValueError:
            continue
        if abs((target_date - row_date).days) != 1:
            continue

        hs = feed.team_score(str(row.get("home_team") or ""), str(target.get("home_en") or ""))
        aws = feed.team_score(str(row.get("away_team") or ""), str(target.get("away_en") or ""))
        if hs < 0.999 or aws < 0.999:
            continue
        candidates.append((target, hs, aws))

    if len(candidates) != 1:
        return None

    target, hs, aws = candidates[0]
    row_for_attach = dict(row)
    row_for_attach["match_date"] = target["match_date"]
    recovered = _legacy_attach(row_for_attach, [target])
    if recovered is None:
        return None

    print(
        "FOREBET_DATE_ROLLOVER_MATCH "
        f"event={target.get('hkjc_event_id','')} "
        f"row_date={row_date_raw} target_date={target.get('match_date','')} "
        f"fixture={row.get('home_team','')} vs {row.get('away_team','')} "
        f"hs={hs:.3f} aws={aws:.3f}",
        flush=True,
    )
    return recovered


_original_attach = _attach_with_safe_date_rollover


def _load_alias_registry() -> int:
    loaded = conflicts = manual_loaded = 0
    sources = (
        (ALIAS_REGISTRY, False),
        (MANUAL_ALIAS, True),
    )
    for path, is_manual in sources:
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                status = "MANUAL" if is_manual else (row.get("status") or "").strip().upper()
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
                    # Manual file is loaded last and is authoritative.
                    feed.ALIASES[alias_key] = canonical_value
                    loaded += 1
                    if is_manual:
                        manual_loaded += 1
    print(
        f"FOREBET_ALIAS_REGISTRY rows={loaded} manual={manual_loaded} "
        f"conflicts_skipped={conflicts}",
        flush=True,
    )
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
                    return _remember_targets(usable)
                print(f"WARN: direct HKJC targets stale age_min={age:.1f}; using snapshot fallback", flush=True)
        except Exception as exc:
            print(f"WARN: direct HKJC targets invalid ({exc}); using snapshot fallback", flush=True)
    print("HKJC_GATE_SOURCE legacy_google_snapshot_fallback", flush=True)
    return _remember_targets(_translate_target_dates(_legacy_load_targets()))


feed.load_hkjc_targets = _load_direct_or_fallback


def _rcnt_count(html: str) -> int:
    return len(re.findall(r'class=["\'][^"\']*\brcnt\b', html or "", flags=re.I))


def _healthy_html(html: str) -> tuple[bool, int]:
    rows = _rcnt_count(html)
    return bool(html and len(html) >= MIN_HEALTHY_BYTES and rows > 0), rows


def _jina_request(url: str, *, no_cache: bool) -> tuple[str | None, int, int]:
    global _JINA_CIRCUIT_OPEN
    if _JINA_CIRCUIT_OPEN:
        return None, 0, 0
    headers = {
        "x-respond-with": "html",
        "x-timeout": "30",
        "User-Agent": "Mozilla/5.0",
    }
    if no_cache:
        headers["x-no-cache"] = "true"
        headers["x-cache-tolerance"] = "0"
    try:
        r = feed.requests.get(JINA_PREFIX + url, headers=headers, timeout=JINA_TIMEOUT)
    except Exception as exc:
        print(f"WARN: Jina request failed no_cache={int(no_cache)} url={url}: {exc}", flush=True)
        return None, 0, 0
    healthy, rows = _healthy_html(r.text)
    if r.status_code == 429:
        _JINA_CIRCUIT_OPEN = True
        print(
            f"FOREBET_JINA_CIRCUIT_OPEN status=429 url={url} "
            "action=skip_remaining_jina_requests",
            flush=True,
        )
    print(
        f"FOREBET_JINA_FETCH no_cache={int(no_cache)} status={r.status_code} "
        f"bytes={len(r.text)} rcnt={rows} healthy={int(healthy)} url={url}",
        flush=True,
    )
    if r.status_code != 200 or not healthy:
        return None, len(r.text), rows
    return r.text, len(r.text), rows


def _jina_text_probe(url: str, label: str) -> str | None:
    """Probe Jina's default text/Markdown mode when forced-HTML is unhealthy."""
    if _JINA_CIRCUIT_OPEN:
        return None
    headers = {
        "x-timeout": "30",
        "User-Agent": "Mozilla/5.0",
        "x-no-cache": "true",
        "x-cache-tolerance": "0",
    }
    try:
        r = feed.requests.get(JINA_PREFIX + url, headers=headers, timeout=JINA_TIMEOUT)
    except Exception as exc:
        print(f"FOREBET_JINA_TEXT_PROBE label={label} error={exc}", flush=True)
        return None
    body = r.text or ""
    lower = body.casefold()
    markers = {
        "home_team": int("home team" in lower),
        "away_team": int("away team" in lower),
        "prob": int("prob" in lower),
        "correct_score": int("correct score" in lower),
        "forebet": int("forebet" in lower),
    }
    preview = " ".join(body[:900].split())
    print(
        f"FOREBET_JINA_TEXT_PROBE label={label} status={r.status_code} "
        f"bytes={len(body)} markers={markers} preview={preview!r}",
        flush=True,
    )
    return body if r.status_code == 200 and len(body) >= 5000 else None


def _jina_html(url: str, label: str) -> str | None:
    if url in _JINA_CACHE:
        return _JINA_CACHE[url]
    html, _, _ = _jina_request(url, no_cache=False)
    if html is None:
        print(f"FOREBET_JINA_RETRY label={label} reason=unhealthy_or_placeholder", flush=True)
        html, _, _ = _jina_request(url, no_cache=True)
    if html is None:
        # Diagnostic/default-mode probe. Forced-HTML has occasionally returned
        # placeholders while Jina's text renderer remained useful.
        if label.startswith("date_"):
            _jina_text_probe(url, label)
        print(f"FOREBET_SOURCE_UNHEALTHY label={label} url={url}", flush=True)
    else:
        print(f"FOREBET_SOURCE_HEALTHY label={label} rcnt={_rcnt_count(html)}", flush=True)
    _JINA_CACHE[url] = html
    return html


def _browser_html(url: str, label: str) -> str | None:
    global _BROWSER_CIRCUIT_OPEN
    """Render one primary Forebet page with the runner's installed Chrome.

    This is a bounded fallback for Jina outages/rate limits. It is intentionally
    not used for every recovery surface, which would create excessive browser
    traffic and increase blocking risk.
    """
    if url in _BROWSER_CACHE:
        return _BROWSER_CACHE[url]
    if _BROWSER_CIRCUIT_OPEN:
        return None

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"FOREBET_BROWSER_UNAVAILABLE label={label} error={exc}", flush=True)
        _BROWSER_CACHE[url] = None
        return None

    html = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel="chrome",
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                java_script_enabled=True,
            )
            page = context.new_page()
            response = page.goto(url, timeout=60_000, wait_until="domcontentloaded")
            status = response.status if response else 0
            if status in (403, 429):
                _BROWSER_CIRCUIT_OPEN = True
                print(
                    f"FOREBET_BROWSER_CIRCUIT_OPEN status={status} label={label} "
                    "action=skip_remaining_browser_requests",
                    flush=True,
                )
                browser.close()
                _BROWSER_CACHE[url] = None
                return None
            try:
                page.wait_for_selector("div.rcnt", timeout=20_000)
            except Exception:
                pass

            # Forebet can lazy-load additional rows behind scrolling/MORE.
            for _ in range(6):
                page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                page.wait_for_timeout(500)
            for _ in range(6):
                try:
                    more = page.locator("#mrows")
                    if more.count() == 0 or not more.first.is_visible():
                        break
                    more.first.click(timeout=3_000)
                    page.wait_for_timeout(700)
                except Exception:
                    break

            html = page.content()
            browser.close()
            healthy, rows = _healthy_html(html)
            print(
                f"FOREBET_BROWSER_FETCH label={label} status={status} "
                f"bytes={len(html or '')} rcnt={rows} healthy={int(healthy)} url={url}",
                flush=True,
            )
            if not healthy:
                html = None
    except Exception as exc:
        print(f"WARN: Forebet browser fallback failed label={label} url={url}: {exc}", flush=True)
        html = None

    _BROWSER_CACHE[url] = html
    return html


def _matched_target_ids(html: str, match_date: str, targets: list[dict]) -> set[str]:
    ids: set[str] = set()
    if not html:
        return ids
    for row in feed.parse_forebet_rows(html, match_date):
        selected = _original_attach(row, targets)
        if selected is not None:
            event_id = str(selected.get("hkjc_event_id") or "").strip()
            if event_id:
                ids.add(event_id)
    return ids


def _fetch_forebet_generic_date(match_date: str):
    """Fetch a dated page, then generic all-predictions pages until targets are covered."""
    date_targets = [t for t in _ACTIVE_TARGETS if t.get("match_date") == match_date]
    required_ids = {str(t.get("hkjc_event_id") or "").strip() for t in date_targets}
    required_ids.discard("")

    parts: list[str] = []
    matched_ids: set[str] = set()
    seen_signatures: set[str] = set()

    dated_url = (
        "https://www.forebet.com/en/football-predictions/"
        f"predictions-1x2/{match_date}/by-league"
    )
    dated = _jina_html(dated_url, f"date_{match_date}")
    if not dated:
        # Jina is a convenience gateway, not a production dependency. If it
        # returns placeholders/429s, render the primary dated page in Chrome.
        dated = _browser_html(dated_url, f"date_{match_date}")
    if dated:
        parts.append(dated)
        matched_ids |= _matched_target_ids(dated, match_date, date_targets)

    missing = required_ids - matched_ids
    for start in range(2, 2 + MAX_GENERIC_PAGES):
        if not missing:
            break
        url = f"https://www.forebet.com/en/football-predictions/predictions-1x2?start={start}"
        html = _jina_html(url, f"global_start_{start}")
        if not html:
            continue
        signature = hashlib.sha1(html.encode("utf-8", errors="ignore")).hexdigest()
        if signature in seen_signatures:
            print(f"FOREBET_GENERIC_DUPLICATE start={start} skipped=1", flush=True)
            continue
        seen_signatures.add(signature)
        parts.append(html)
        matched_ids |= _matched_target_ids(html, match_date, date_targets)
        missing = required_ids - matched_ids
        print(
            f"FOREBET_GENERIC_PROGRESS date={match_date} start={start} "
            f"covered={len(matched_ids)}/{len(required_ids)} missing={len(missing)}",
            flush=True,
        )

    if not parts:
        print(f"ERROR: zero healthy free Forebet source pages for {match_date}", file=feed.sys.stderr)
        return None, 0
    print(
        f"FOREBET_DATE_COVERAGE date={match_date} matched={len(matched_ids)} "
        f"targets={len(required_ids)} missing={len(required_ids - matched_ids)} scraperapi_credits=0",
        flush=True,
    )
    return "\n".join(parts), 0


feed.fetch_forebet_date = _fetch_forebet_generic_date


def _attach_only_usable(row, targets):
    probs = (row.get("prob_home"), row.get("prob_draw"), row.get("prob_away"))
    if not all(isinstance(v, (int, float)) for v in probs):
        return None
    return _original_attach(row, targets)


feed.attach_hkjc_target = _attach_only_usable


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def _snapshot_previous_current() -> None:
    global _PREVIOUS_CURRENT
    _PREVIOUS_CURRENT, _ = _read_csv(CURRENT_FEED)
    print(f"FOREBET_PREVIOUS_CURRENT rows={len(_PREVIOUS_CURRENT)}", flush=True)


def _carry_forward_active_models() -> int:
    """Preserve last-known model rows for still-active HKJC events missing from a partial refresh."""
    if not _PREVIOUS_CURRENT or not _ACTIVE_TARGETS or not CURRENT_FEED.exists():
        return 0
    new_rows, new_fields = _read_csv(CURRENT_FEED)
    if not new_fields:
        return 0

    active_by_id = {
        str(t.get("hkjc_event_id") or "").strip(): t
        for t in _ACTIVE_TARGETS
        if str(t.get("hkjc_event_id") or "").strip()
    }
    new_by_id = {
        str(r.get("hkjc_event_id") or "").strip(): r
        for r in new_rows
        if str(r.get("hkjc_event_id") or "").strip()
    }
    old_by_id = {
        str(r.get("hkjc_event_id") or "").strip(): r
        for r in _PREVIOUS_CURRENT
        if str(r.get("hkjc_event_id") or "").strip()
    }

    carried = 0
    for event_id, target in active_by_id.items():
        if event_id in new_by_id or event_id not in old_by_id:
            continue
        old = dict(old_by_id[event_id])
        if not all((old.get(k) or "").strip() for k in ("prob_home", "prob_draw", "prob_away")):
            continue
        # Refresh target identity/market metadata while intentionally preserving the
        # old model timestamp/probabilities so stale model age remains observable.
        old.update({
            "hkjc_event_id": event_id,
            "hkjc_league": target.get("league_zh", old.get("hkjc_league", "")),
            "hkjc_home_team": target.get("home_en", old.get("hkjc_home_team", "")),
            "hkjc_away_team": target.get("away_en", old.get("hkjc_away_team", "")),
            "hkjc_home_zh": target.get("home_zh", old.get("hkjc_home_zh", "")),
            "hkjc_away_zh": target.get("away_zh", old.get("hkjc_away_zh", "")),
            "hkjc_kickoff_hkt": target.get("kickoff_hkt", old.get("hkjc_kickoff_hkt", "")),
            "hkjc_had_home": target.get("had_home", old.get("hkjc_had_home", "")),
            "hkjc_had_draw": target.get("had_draw", old.get("hkjc_had_draw", "")),
            "hkjc_had_away": target.get("had_away", old.get("hkjc_had_away", "")),
        })
        new_by_id[event_id] = old
        carried += 1

    if carried == 0:
        print("FOREBET_ACTIVE_CARRY_FORWARD rows=0", flush=True)
        return 0

    fields = list(new_fields)
    for row in _PREVIOUS_CURRENT:
        for key in row.keys():
            if key not in fields:
                fields.append(key)
    rows = sorted(
        new_by_id.values(),
        key=lambda r: (r.get("hkjc_kickoff_hkt", ""), r.get("hkjc_event_id", "")),
    )
    tmp = CURRENT_FEED.with_suffix(".carry.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: row.get(k, "") for k in fields} for row in rows)
    tmp.replace(CURRENT_FEED)
    print(
        f"FOREBET_ACTIVE_CARRY_FORWARD rows={carried} final_current={len(rows)} "
        f"active_targets={len(active_by_id)}",
        flush=True,
    )
    return carried


def main() -> int:
    _snapshot_previous_current()
    code = feed.main()
    if code != 0:
        return code
    _carry_forward_active_models()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
