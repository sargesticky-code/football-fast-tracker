"""Target-aware recovery for HKJC fixtures omitted from Forebet's dated indexes.

Durable recovery layers:
1) the normal dated/all-predictions pages from ``run_selective``;
2) Forebet's /values first-party index;
3) broad Forebet region/competition list indexes, independent of HKJC league codes;
4) cards/corners indexes for match-detail discovery;
5) a dedicated match-detail Markdown parser that does not require ``div.rcnt``.

The last point is important: Forebet match-detail pages have a different page
shape from prediction-list pages. Treating a detail page as unhealthy merely
because it has no ``div.rcnt`` silently drops valid models. This module keeps
list-page and detail-page health/parsing separate.
"""
from __future__ import annotations

import html as html_lib
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE = "https://www.forebet.com"
MAX_DETAIL_RECOVERY = 48  # bounded; earliest HKJC kickoffs first, avoids unlimited detail fan-out
MATCH_LINK_RE = re.compile(r"/en/football/matches/", re.I)
DETAIL_MIN_TEXT = 1200

# Broad first-party lists are generic recovery surfaces, not league-specific
# routing. They are fetched only while HKJC targets remain unresolved and are
# cached by run_selective, so the same page is not repeatedly downloaded.
BROAD_INDEXES = [
    ("america", "https://www.forebet.com/en/prediction-lists/america"),
    ("national_cups", "https://www.forebet.com/en/prediction-lists/national-cups"),
    ("international", "https://www.forebet.com/en/prediction-lists/international"),
    ("asia", "https://www.forebet.com/en/prediction-lists/asia"),
    ("africa", "https://www.forebet.com/en/prediction-lists/africa"),
    ("united_kingdom", "https://www.forebet.com/en/prediction-lists/united-kingdom"),
    ("top_europe", "https://www.forebet.com/en/prediction-lists/top-europe"),
    ("all_europe", "https://www.forebet.com/en/prediction-lists/all-europe"),
    ("australia", "https://www.forebet.com/en/prediction-lists/australia"),
]

_DETAIL_CACHE: dict[str, str | None] = {}


def _clean_text(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _row_teams(row) -> tuple[str, str]:
    home = _clean_text(row.select_one("span.homeTeam span[itemprop='name']"))
    away = _clean_text(row.select_one("span.awayTeam span[itemprop='name']"))
    if not home:
        home = _clean_text(row.select_one(".homeTeam"))
    if not away:
        away = _clean_text(row.select_one(".awayTeam"))
    if not home or not away:
        meta = row.find("meta", attrs={"itemprop": "name"})
        content = (meta.get("content") or "").strip() if meta else ""
        if " vs " in content.lower():
            parts = re.split(r"\s+vs\s+", content, maxsplit=1, flags=re.I)
            if len(parts) == 2:
                home, away = parts[0].strip(), parts[1].strip()
    return home, away


def _detail_url(row) -> str:
    anchor = row.find("a", href=MATCH_LINK_RE)
    if anchor and anchor.get("href"):
        return urljoin(BASE, str(anchor.get("href")))
    for anchor in row.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if "/football/matches/" in href:
            return urljoin(BASE, href)
    return ""


def _usable_ids(production, html: str | None, match_date: str, targets: list[dict]) -> set[str]:
    ids: set[str] = set()
    if not html:
        return ids
    for row in production.feed.parse_forebet_rows(html, match_date):
        probs = (row.get("prob_home"), row.get("prob_draw"), row.get("prob_away"))
        if not all(isinstance(v, (int, float)) for v in probs):
            continue
        selected = production._original_attach(row, targets)
        if selected is not None:
            event_id = str(selected.get("hkjc_event_id") or "").strip()
            if event_id:
                ids.add(event_id)
    return ids


def _discover(production, html: str, missing_targets: list[dict]) -> dict[str, str]:
    """Discover match-detail URLs from any Forebet list-page rcnt rows."""
    soup = BeautifulSoup(html or "", "lxml")
    candidates: dict[str, tuple[float, str]] = {}

    for row in soup.select("div.rcnt"):
        home, away = _row_teams(row)
        url = _detail_url(row)
        if not home or not away or not url:
            continue
        for target in missing_targets:
            event_id = str(target.get("hkjc_event_id") or "").strip()
            if not event_id:
                continue
            hs = production.feed.team_score(home, target.get("home_en", ""))
            aws = production.feed.team_score(away, target.get("away_en", ""))
            avg = (hs + aws) / 2
            if hs < 0.68 or aws < 0.68 or avg < 0.76:
                continue
            old = candidates.get(event_id)
            if old is None or avg > old[0]:
                candidates[event_id] = (avg, url)

    return {event_id: value[1] for event_id, value in candidates.items()}


def _fetch_detail_markdown(production, url: str, label: str) -> str | None:
    """Fetch a match-detail page with detail-specific health checks."""
    if url in _DETAIL_CACHE:
        return _DETAIL_CACHE[url]

    headers = {
        "X-Timeout": "30",
        "User-Agent": "Mozilla/5.0",
        "X-No-Cache": "true",
        "X-Cache-Tolerance": "0",
    }
    try:
        response = production.feed.requests.get(
            production.JINA_PREFIX + url,
            headers=headers,
            timeout=production.JINA_TIMEOUT,
        )
    except Exception as exc:
        print(f"WARN Forebet detail text failed label={label}: {exc}", flush=True)
        _DETAIL_CACHE[url] = None
        return None

    body = response.text or ""
    marker = bool(
        re.search(r"\bProb\.\s*%|\bProbability\s*%", body, flags=re.I)
        and re.search(r"\b1\s+X\s+2\b", body, flags=re.I)
    )
    healthy = response.status_code == 200 and len(body) >= DETAIL_MIN_TEXT and marker
    print(
        f"FOREBET_DETAIL_FETCH label={label} status={response.status_code} "
        f"bytes={len(body)} healthy={int(healthy)}",
        flush=True,
    )
    result = body if healthy else None
    _DETAIL_CACHE[url] = result
    return result


def _plain_markdown_line(value: str) -> str:
    value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = value.replace("**", "").replace("__", "")
    value = re.sub(r"^#+\s*", "", value)
    return " ".join(value.split()).strip()


def _parse_probability_triple(line: str) -> tuple[int, int, int] | None:
    numbers = [int(x) for x in re.findall(r"(?<!\d)(\d{1,3})(?!\d)", line)]
    if len(numbers) != 3:
        return None
    if any(x < 0 or x > 100 for x in numbers) or sum(numbers) != 100:
        return None
    return numbers[0], numbers[1], numbers[2]


def _parse_detail_model(production, body: str, target: dict, match_date: str) -> dict[str, str] | None:
    """Parse the first full-time 1X2 prediction block from rendered detail text."""
    raw_lines = [line.strip() for line in body.splitlines() if line.strip()]
    lines = [_plain_markdown_line(line) for line in raw_lines]
    lines = [line for line in lines if line]
    if not lines:
        return None

    source_home = ""
    source_away = ""
    for line in lines[:80]:
        match = re.match(r"(.+?)\s+VS\s+(.+)$", line, flags=re.I)
        if match:
            source_home = match.group(1).strip()
            source_away = match.group(2).strip()
            break

    if not source_home or not source_away:
        source_home = str(target.get("home_en") or "").strip()
        source_away = str(target.get("away_en") or "").strip()

    hs = production.feed.team_score(source_home, target.get("home_en", ""))
    aws = production.feed.team_score(source_away, target.get("away_en", ""))
    if hs < 0.68 or aws < 0.68 or (hs + aws) / 2 < 0.76:
        return None

    section = -1
    for index, line in enumerate(lines[:220]):
        if re.search(r"(^|\s)1\s+X\s+2($|\s)", line, flags=re.I):
            section = index
            break
    if section < 0:
        return None

    prob_index = -1
    probs: tuple[int, int, int] | None = None
    for index in range(section + 1, min(len(lines), section + 80)):
        if index > section + 4 and "Under/Over" in lines[index]:
            break
        candidate = _parse_probability_triple(lines[index])
        if candidate:
            probs = candidate
            prob_index = index
            break
    if probs is None:
        return None

    prediction = ""
    score = ""
    prediction_index = -1
    for index in range(prob_index + 1, min(len(lines), prob_index + 12)):
        line = lines[index]
        match = re.match(r"^([12Xx])(?:\s+(\d+)\s*-\s*(\d+))?(?:\s.*)?$", line)
        if not match:
            continue
        prediction = match.group(1).upper()
        prediction_index = index
        if match.group(2) is not None and match.group(3) is not None:
            score = f"{match.group(2)} - {match.group(3)}"
        break
    if not prediction:
        return None

    score_index = prediction_index
    if not score:
        for index in range(prediction_index + 1, min(len(lines), prediction_index + 8)):
            match = re.search(r"(?<!\d)(\d+)\s*-\s*(\d+)(?!\d)", lines[index])
            if match:
                score = f"{match.group(1)} - {match.group(2)}"
                score_index = index
                break

    avg_goals = ""
    for index in range(score_index + 1, min(len(lines), score_index + 7)):
        match = re.fullmatch(r"(\d{1,2}\.\d{1,2})", lines[index])
        if match:
            avg_goals = match.group(1)
            break

    return {
        "home": source_home,
        "away": source_away,
        "home_prob": str(probs[0]),
        "draw_prob": str(probs[1]),
        "away_prob": str(probs[2]),
        "prediction": prediction,
        "score": score,
        "avg_goals": avg_goals,
        "match_date": match_date,
        "kickoff": str(target.get("kickoff_hkt") or ""),
        "league": str(target.get("league_zh") or ""),
    }


def _synthetic_rcnt(model: dict[str, str]) -> str:
    """Render a minimal standard rcnt row for the existing Forebet parser."""
    esc = html_lib.escape
    return (
        '<div class="rcnt">'
        f'<span class="shortTag">{esc(model["league"])}</span>'
        f'<span class="homeTeam"><span itemprop="name">{esc(model["home"])}</span></span>'
        f'<span class="awayTeam"><span itemprop="name">{esc(model["away"])}</span></span>'
        f'<time datetime="{esc(model["match_date"])}"></time>'
        f'<span class="date_bah">{esc(model["kickoff"])}</span>'
        '<div class="fprc">'
        f'<span>{esc(model["home_prob"])}</span>'
        f'<span>{esc(model["draw_prob"])}</span>'
        f'<span>{esc(model["away_prob"])}</span>'
        '</div>'
        f'<span class="forepr"><span>{esc(model["prediction"])}</span></span>'
        f'<div class="predict_score">{esc(model["score"])}</div>'
        f'<div class="avg_sc">{esc(model["avg_goals"])}</div>'
        '</div>'
    )


def _league_coverage(date_targets: list[dict], covered_ids: set[str], match_date: str) -> None:
    buckets: dict[str, list[str]] = {}
    for target in date_targets:
        league = str(target.get("league_zh") or "UNKNOWN").strip() or "UNKNOWN"
        event_id = str(target.get("hkjc_event_id") or "").strip()
        if event_id:
            buckets.setdefault(league, []).append(event_id)
    for league, event_ids in sorted(buckets.items()):
        matched = sum(event_id in covered_ids for event_id in event_ids)
        print(
            f"FOREBET_LEAGUE_COVERAGE date={match_date} league={league} "
            f"matched={matched}/{len(event_ids)}",
            flush=True,
        )


def install(production) -> None:
    original_fetch = production._fetch_forebet_generic_date

    def fetch_with_target_recovery(match_date: str):
        html, cost = original_fetch(match_date)
        date_targets = [
            t for t in production._ACTIVE_TARGETS
            if t.get("match_date") == match_date
        ]
        required = {
            str(t.get("hkjc_event_id") or "").strip()
            for t in date_targets
            if str(t.get("hkjc_event_id") or "").strip()
        }
        covered = _usable_ids(production, html, match_date, date_targets)
        initially_missing = required - covered
        missing_ids = set(initially_missing)
        if not missing_ids:
            _league_coverage(date_targets, covered, match_date)
            print(
                f"FOREBET_TARGET_RECOVERY date={match_date} needed=0 recovered=0 unresolved=0",
                flush=True,
            )
            return html, cost

        extra_parts: list[str] = []
        target_by_id = {
            str(t.get("hkjc_event_id") or "").strip(): t for t in date_targets
        }
        discovered: dict[str, str] = {}

        values_html = production._jina_html(
            "https://www.forebet.com/en/values", f"recovery_values_{match_date}"
        )
        if values_html:
            values_ids = _usable_ids(production, values_html, match_date, date_targets)
            new_values = values_ids & missing_ids
            if new_values:
                extra_parts.append(values_html)
                covered |= new_values
                missing_ids = required - covered
            found = _discover(
                production,
                values_html,
                [target_by_id[x] for x in sorted(missing_ids) if x in target_by_id],
            )
            discovered.update(found)
            print(
                f"FOREBET_VALUE_RECOVERY date={match_date} "
                f"matched={len(values_ids)} new={len(new_values)} "
                f"discovered={len(found)} remaining={len(missing_ids)}",
                flush=True,
            )

        # Forebet exposes a dedicated Tomorrow 1X2 surface.  The normal dated
        # index can lag or omit future fixtures even when their prediction page is
        # already live, so use Tomorrow as a first-class recovery source for a
        # future UTC match date.  One cached page only; no per-event fan-out.
        today_utc = datetime.now(timezone.utc).date().isoformat()
        if missing_ids and match_date > today_utc:
            tomorrow_url = (
                "https://www.forebet.com/en/"
                "football-tips-and-predictions-for-tomorrow/predictions-1x2/by-league"
            )
            tomorrow_html = production._jina_html(
                tomorrow_url, f"recovery_tomorrow_{match_date}"
            )
            if tomorrow_html:
                usable = _usable_ids(production, tomorrow_html, match_date, date_targets)
                new_ids = usable & missing_ids
                if new_ids:
                    extra_parts.append(tomorrow_html)
                    covered |= new_ids
                    missing_ids = required - covered
                still_missing = [
                    target_by_id[event_id]
                    for event_id in sorted(missing_ids - set(discovered))
                    if event_id in target_by_id
                ]
                found = _discover(production, tomorrow_html, still_missing)
                discovered.update(found)
                print(
                    f"FOREBET_TOMORROW_RECOVERY date={match_date} "
                    f"new={len(new_ids)} discovered={len(found)} "
                    f"remaining={len(missing_ids)}",
                    flush=True,
                )

        for kind, index_url in BROAD_INDEXES:
            if not missing_ids:
                break
            index_html = production._jina_html(
                index_url, f"recovery_list_{kind}_{match_date}"
            )
            if not index_html:
                continue
            usable = _usable_ids(production, index_html, match_date, date_targets)
            new_ids = usable & missing_ids
            if new_ids:
                extra_parts.append(index_html)
                covered |= new_ids
                missing_ids = required - covered

            still_missing = [
                target_by_id[event_id]
                for event_id in sorted(missing_ids - set(discovered))
                if event_id in target_by_id
            ]
            found = _discover(production, index_html, still_missing)
            discovered.update(found)
            print(
                f"FOREBET_LIST_RECOVERY date={match_date} source={kind} "
                f"new={len(new_ids)} discovered={len(found)} "
                f"remaining={len(missing_ids)}",
                flush=True,
            )

        index_urls = [
            (
                "cards",
                "https://www.forebet.com/en/football-predictions/"
                f"cards/{match_date}",
            ),
            (
                "corners",
                "https://www.forebet.com/en/football-predictions/"
                f"corners/{match_date}/by-league",
            ),
        ]

        for kind, index_url in index_urls:
            still_missing = [
                target_by_id[event_id]
                for event_id in sorted(missing_ids - set(discovered))
                if event_id in target_by_id
            ]
            if not still_missing:
                break
            index_html = production._jina_html(
                index_url, f"recovery_{kind}_{match_date}"
            )
            if not index_html:
                continue
            found = _discover(production, index_html, still_missing)
            discovered.update(found)
            print(
                f"FOREBET_TARGET_DISCOVERY date={match_date} source={kind} "
                f"found={len(found)} cumulative={len(discovered)} "
                f"missing={len(missing_ids)}",
                flush=True,
            )

        detail_parts: list[str] = []
        recovered_detail: set[str] = set()

        # Detail recovery is deliberately capped to protect Forebet from excess
        # requests, but the cap must be spent on the most time-sensitive HKJC
        # fixtures.  Sorting by event ID can starve matches that are about to
        # start while recovering later fixtures first.  Prioritise the earliest
        # kickoff, then event ID for deterministic ordering.
        detail_candidates = [
            event_id for event_id in discovered
            if event_id in missing_ids
        ]
        detail_candidates.sort(
            key=lambda event_id: (
                str(target_by_id.get(event_id, {}).get("kickoff_hkt") or "9999-12-31T23:59:59+08:00"),
                event_id,
            )
        )
        print(
            "FOREBET_DETAIL_PRIORITY "
            f"date={match_date} candidates={len(detail_candidates)} "
            f"cap={MAX_DETAIL_RECOVERY} "
            f"first={','.join(detail_candidates[:5])}",
            flush=True,
        )

        for event_id in detail_candidates[:MAX_DETAIL_RECOVERY]:
            target = target_by_id.get(event_id)
            if target is None:
                continue
            detail_url = discovered[event_id]
            detail_text = _fetch_detail_markdown(
                production, detail_url, f"target_{event_id}_{match_date}"
            )
            if not detail_text:
                continue
            model = _parse_detail_model(production, detail_text, target, match_date)
            if model is None:
                print(
                    f"FOREBET_DETAIL_PARSE_FAIL date={match_date} event={event_id}",
                    flush=True,
                )
                continue
            synthetic = _synthetic_rcnt(model)
            if event_id in _usable_ids(production, synthetic, match_date, [target]):
                detail_parts.append(synthetic)
                recovered_detail.add(event_id)
                print(
                    f"FOREBET_DETAIL_RECOVERED date={match_date} event={event_id} "
                    f"fixture={model['home']} vs {model['away']}",
                    flush=True,
                )

        covered |= recovered_detail
        unresolved = required - covered
        final_html = "\n".join(
            [part for part in (html or "", *extra_parts, *detail_parts) if part]
        )

        _league_coverage(date_targets, covered, match_date)
        print(
            f"FOREBET_TARGET_RECOVERY date={match_date} "
            f"needed={len(initially_missing)} discovered={len(discovered)} "
            f"recovered={len(initially_missing - unresolved)} "
            f"unresolved={len(unresolved)}",
            flush=True,
        )
        if unresolved:
            print(
                "FOREBET_TARGET_UNRESOLVED " + ",".join(sorted(unresolved)),
                flush=True,
            )
            for event_id in sorted(unresolved):
                target = target_by_id.get(event_id, {})
                print(
                    f"FOREBET_NO_MODEL event={event_id} "
                    f"league={target.get('league_zh','')} "
                    f"fixture={target.get('home_en','')} vs {target.get('away_en','')}",
                    flush=True,
                )
        return (final_html or None), cost

    production.feed.fetch_forebet_date = fetch_with_target_recovery
