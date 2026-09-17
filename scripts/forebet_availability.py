"""Classify Forebet availability for every active HKJC model target.

This layer runs after all prediction recovery.  It distinguishes three states:
- MODEL: a usable Forebet 1X2 model was recovered;
- FIXTURE_ONLY: Forebet recognises the fixture on its livescore surface but no
  usable prediction model was found;
- UNRESOLVED: neither a model nor reliable fixture-presence evidence was found.

The classification is written back to hkjc_targets.csv so source gaps are
explicit and durable instead of appearing as unexplained blank model cells.
No probabilities or predictions are invented for FIXTURE_ONLY fixtures.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")
LIVESCORE_URL = "https://www.forebet.com/en/livescore"
STATE_FIELD = "forebet_state"
REASON_FIELD = "forebet_reason"
_LIVESCORE_CACHE: str | None | bool = False


def _clean_line(value: str) -> str:
    value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = value.replace("**", "").replace("__", "")
    value = re.sub(r"^#+\s*", "", value)
    return " ".join(value.split()).strip()


def _model_ids(production, html: str | None, match_date: str, targets: list[dict]) -> set[str]:
    ids: set[str] = set()
    if not html:
        return ids
    for row in production.feed.parse_forebet_rows(html, match_date):
        probs = (row.get("prob_home"), row.get("prob_draw"), row.get("prob_away"))
        if not all(isinstance(v, (int, float)) for v in probs):
            continue
        selected = production._original_attach(row, targets)
        if selected is None:
            continue
        event_id = str(selected.get("hkjc_event_id") or "").strip()
        if event_id:
            ids.add(event_id)
    return ids


def _fetch_livescore(production) -> str | None:
    global _LIVESCORE_CACHE
    if _LIVESCORE_CACHE is not False:
        return _LIVESCORE_CACHE if isinstance(_LIVESCORE_CACHE, str) else None

    headers = {
        "X-Timeout": "30",
        "User-Agent": "Mozilla/5.0",
        "X-No-Cache": "true",
        "X-Cache-Tolerance": "0",
    }
    try:
        response = production.feed.requests.get(
            production.JINA_PREFIX + LIVESCORE_URL,
            headers=headers,
            timeout=production.JINA_TIMEOUT,
        )
    except Exception as exc:
        print(f"WARN Forebet livescore availability fetch failed: {exc}", flush=True)
        _LIVESCORE_CACHE = None
        return None

    body = response.text or ""
    healthy = response.status_code == 200 and len(body) >= 5000
    print(
        f"FOREBET_AVAILABILITY_LIVESCORE status={response.status_code} "
        f"bytes={len(body)} healthy={int(healthy)}",
        flush=True,
    )
    _LIVESCORE_CACHE = body if healthy else None
    return body if healthy else None


def _fixture_ids(production, body: str | None, targets: list[dict]) -> set[str]:
    if not body:
        return set()
    lines = [_clean_line(line) for line in body.splitlines() if line.strip()]
    lines = [line for line in lines if line]
    found: set[str] = set()

    for target in targets:
        event_id = str(target.get("hkjc_event_id") or "").strip()
        home = str(target.get("home_en") or "").strip()
        away = str(target.get("away_en") or "").strip()
        if not event_id or not home or not away:
            continue

        best = 0.0
        for i, line in enumerate(lines):
            hs = production.feed.team_score(line, home)
            if hs < 0.68:
                continue
            # Livescore renders a compact fixture block: time/status, home,
            # score/separator, away, id.  Keep the window tight so standings
            # or unrelated team mentions cannot establish fixture presence.
            for j in range(i + 1, min(len(lines), i + 6)):
                aws = production.feed.team_score(lines[j], away)
                avg = (hs + aws) / 2
                if hs >= 0.68 and aws >= 0.68 and avg >= 0.76:
                    best = max(best, avg)
            if best >= 0.90:
                break
        if best >= 0.76:
            found.add(event_id)
    return found


def _write_states(production, states: dict[str, tuple[str, str]]) -> None:
    path = Path(production.DIRECT_TARGETS)
    if not path.exists():
        return
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if STATE_FIELD not in fields:
        fields.append(STATE_FIELD)
    if REASON_FIELD not in fields:
        fields.append(REASON_FIELD)

    for row in rows:
        event_id = str(row.get("hkjc_event_id") or "").strip()
        if event_id in states:
            row[STATE_FIELD], row[REASON_FIELD] = states[event_id]

    tmp = path.with_suffix(".availability.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def install(production) -> None:
    original_fetch = production.feed.fetch_forebet_date

    def fetch_with_availability(match_date: str):
        html, cost = original_fetch(match_date)
        targets = [
            target for target in production._ACTIVE_TARGETS
            if target.get("match_date") == match_date
        ]
        if not targets:
            return html, cost

        model_ids = _model_ids(production, html, match_date, targets)
        unresolved_targets = [
            target for target in targets
            if str(target.get("hkjc_event_id") or "").strip() not in model_ids
        ]
        fixture_ids: set[str] = set()
        if unresolved_targets:
            fixture_ids = _fixture_ids(
                production,
                _fetch_livescore(production),
                unresolved_targets,
            )

        states: dict[str, tuple[str, str]] = {}
        for target in targets:
            event_id = str(target.get("hkjc_event_id") or "").strip()
            if not event_id:
                continue
            if event_id in model_ids:
                state = "MODEL"
                reason = "usable_forebet_prediction_model"
            elif event_id in fixture_ids:
                state = "FIXTURE_ONLY"
                reason = "forebet_livescore_fixture_without_usable_prediction_model"
            else:
                state = "UNRESOLVED"
                reason = "not_resolved_on_forebet_prediction_or_livescore_surfaces"
            states[event_id] = (state, reason)
            if state != "MODEL":
                print(
                    f"FOREBET_{state} event={event_id} "
                    f"league={target.get('league_zh','')} "
                    f"fixture={target.get('home_en','')} vs {target.get('away_en','')}",
                    flush=True,
                )

        _write_states(production, states)
        print(
            f"FOREBET_AVAILABILITY date={match_date} targets={len(targets)} "
            f"model={sum(v[0] == 'MODEL' for v in states.values())} "
            f"fixture_only={sum(v[0] == 'FIXTURE_ONLY' for v in states.values())} "
            f"unresolved={sum(v[0] == 'UNRESOLVED' for v in states.values())} "
            f"checked_at={datetime.now(HKT).isoformat(timespec='seconds')}",
            flush=True,
        )
        return html, cost

    production.feed.fetch_forebet_date = fetch_with_availability
