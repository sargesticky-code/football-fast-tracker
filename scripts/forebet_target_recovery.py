"""Target-aware recovery for HKJC fixtures omitted from Forebet's 1X2 index pages.

Forebet's dated 1X2 page does not always expose every league in the first
rendered batch. Recovery therefore has two generic layers:
1) append Forebet's own current 1X2 value index when it supplies usable models;
2) use date-wide cards/corners indexes only to discover match-detail URLs for
   still-missing HKJC targets, then read the 1X2 model from those detail pages.
No country/league-specific route table is required.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE = "https://www.forebet.com"
MAX_DETAIL_RECOVERY = 24
MATCH_LINK_RE = re.compile(r"/en/football/matches/", re.I)


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
        missing_ids = required - covered
        if not missing_ids:
            print(
                f"FOREBET_TARGET_RECOVERY date={match_date} needed=0 recovered=0 unresolved=0",
                flush=True,
            )
            return html, cost

        extra_parts: list[str] = []

        # Forebet's /values page is another first-party 1X2 index and often
        # exposes leagues omitted from the first dated 1X2 render. Because the
        # normal HKJC date/team gate is still applied, unrelated rows are ignored.
        values_html = production._jina_html(
            "https://www.forebet.com/en/values", f"recovery_values_{match_date}"
        )
        if values_html:
            values_ids = _usable_ids(production, values_html, match_date, date_targets)
            new_values = (values_ids & missing_ids)
            if new_values:
                extra_parts.append(values_html)
                covered |= new_values
                missing_ids = required - covered
            print(
                f"FOREBET_VALUE_RECOVERY date={match_date} "
                f"matched={len(values_ids)} new={len(new_values)} "
                f"remaining={len(missing_ids)}",
                flush=True,
            )

        if not missing_ids:
            final_html = "\n".join(
                [part for part in (html or "", *extra_parts) if part]
            )
            print(
                f"FOREBET_TARGET_RECOVERY date={match_date} needed={len(required - _usable_ids(production, html, match_date, date_targets))} "
                f"recovered={len(required - covered)} unresolved=0",
                flush=True,
            )
            return (final_html or None), cost

        target_by_id = {
            str(t.get("hkjc_event_id") or "").strip(): t for t in date_targets
        }
        discovered: dict[str, str] = {}
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
                f"found={len(found)} cumulative={len(discovered)} missing={len(missing_ids)}",
                flush=True,
            )

        detail_parts: list[str] = []
        recovered_detail: set[str] = set()
        for event_id in sorted(discovered)[:MAX_DETAIL_RECOVERY]:
            detail_url = discovered[event_id]
            detail_html = production._jina_html(
                detail_url, f"target_{event_id}_{match_date}"
            )
            if not detail_html:
                continue
            target = target_by_id.get(event_id)
            if target is None:
                continue
            if event_id in _usable_ids(production, detail_html, match_date, [target]):
                detail_parts.append(detail_html)
                recovered_detail.add(event_id)

        recovered_total = (required - missing_ids) | recovered_detail
        unresolved = required - covered - recovered_detail
        final_html = "\n".join(
            [part for part in (html or "", *extra_parts, *detail_parts) if part]
        )
        print(
            f"FOREBET_TARGET_RECOVERY date={match_date} needed={len(required - _usable_ids(production, html, match_date, date_targets))} "
            f"discovered={len(discovered)} recovered={len(recovered_total)} "
            f"unresolved={len(unresolved)}",
            flush=True,
        )
        if unresolved:
            print(
                "FOREBET_TARGET_UNRESOLVED " + ",".join(sorted(unresolved)),
                flush=True,
            )
        return (final_html or None), cost

    production.feed.fetch_forebet_date = fetch_with_target_recovery
