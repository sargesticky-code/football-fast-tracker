"""Classify Forebet availability for every active HKJC model target.

This layer runs after all prediction recovery. It distinguishes three states:
- MODEL: a usable Forebet 1X2 model was recovered;
- FIXTURE_ONLY: Forebet recognises the fixture but no usable prediction model
  was found;
- UNRESOLVED: neither a model nor reliable fixture-presence evidence was found.

Availability is written to its own Forebet-owned CSV. HKJC feeds remain owned by
the high-frequency HKJC workflow, preventing cross-workflow write conflicts.
A previously observed FIXTURE_ONLY state is retained while the HKJC target stays
active, because Forebet's live-score surface naturally drops fixtures over time.
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
_LIVESCORE_CACHE: str | None | bool = False
_AVAILABILITY: dict[str, dict[str, str]] = {}
_PREVIOUS_AVAILABILITY: dict[str, dict[str, str]] = {}
_PREVIOUS_LOADED = False

FIELDS = [
    "checked_at_hkt", "match_date", "kickoff_hkt", "hkjc_event_id", "league_zh",
    "home_en", "away_en", "state", "reason",
]


def _availability_path(production) -> Path:
    return Path(production.DIRECT_TARGETS).parent / "forebet_availability.csv"


def _load_previous_availability(production) -> dict[str, dict[str, str]]:
    global _PREVIOUS_LOADED
    if _PREVIOUS_LOADED:
        return _PREVIOUS_AVAILABILITY
    _PREVIOUS_LOADED = True
    path = _availability_path(production)
    if not path.exists():
        print("FOREBET_AVAILABILITY_PREVIOUS rows=0 status=missing", flush=True)
        return _PREVIOUS_AVAILABILITY
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                event_id = str(row.get("hkjc_event_id") or "").strip()
                if event_id:
                    _PREVIOUS_AVAILABILITY[event_id] = dict(row)
    except Exception as exc:
        print(f"WARN Forebet previous availability read failed: {exc}", flush=True)
        return _PREVIOUS_AVAILABILITY
    print(
        f"FOREBET_AVAILABILITY_PREVIOUS rows={len(_PREVIOUS_AVAILABILITY)} status=loaded",
        flush=True,
    )
    return _PREVIOUS_AVAILABILITY


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


def _write_availability(production) -> None:
    path = _availability_path(production)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(
        _AVAILABILITY.values(),
        key=lambda row: (row.get("kickoff_hkt", ""), row.get("hkjc_event_id", "")),
    )
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
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

        previous = _load_previous_availability(production)
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

        checked_at = datetime.now(HKT).isoformat(timespec="seconds")
        counts = {"MODEL": 0, "FIXTURE_ONLY": 0, "UNRESOLVED": 0}
        retained_fixture_only = 0
        for target in targets:
            event_id = str(target.get("hkjc_event_id") or "").strip()
            if not event_id:
                continue
            old_state = str(previous.get(event_id, {}).get("state") or "").strip().upper()
            if event_id in model_ids:
                state = "MODEL"
                reason = "usable_forebet_prediction_model"
            elif event_id in fixture_ids:
                state = "FIXTURE_ONLY"
                reason = "forebet_livescore_fixture_without_usable_prediction_model"
            elif old_state == "FIXTURE_ONLY":
                # Livescore is ephemeral evidence. Once the exact active HKJC
                # fixture was observed on Forebet, preserve that evidence until
                # the target leaves the active modelling window.
                state = "FIXTURE_ONLY"
                reason = "previously_observed_forebet_fixture_without_prediction_model"
                retained_fixture_only += 1
            else:
                state = "UNRESOLVED"
                reason = "not_resolved_on_forebet_prediction_or_livescore_surfaces"
            counts[state] += 1
            _AVAILABILITY[event_id] = {
                "checked_at_hkt": checked_at,
                "match_date": str(target.get("match_date") or ""),
                "kickoff_hkt": str(target.get("kickoff_hkt") or ""),
                "hkjc_event_id": event_id,
                "league_zh": str(target.get("league_zh") or ""),
                "home_en": str(target.get("home_en") or ""),
                "away_en": str(target.get("away_en") or ""),
                "state": state,
                "reason": reason,
            }
            if state != "MODEL":
                print(
                    f"FOREBET_{state} event={event_id} "
                    f"league={target.get('league_zh','')} "
                    f"fixture={target.get('home_en','')} vs {target.get('away_en','')} "
                    f"reason={reason}",
                    flush=True,
                )

        _write_availability(production)
        print(
            f"FOREBET_AVAILABILITY date={match_date} targets={len(targets)} "
            f"model={counts['MODEL']} fixture_only={counts['FIXTURE_ONLY']} "
            f"unresolved={counts['UNRESOLVED']} retained_fixture_only={retained_fixture_only} "
            f"checked_at={checked_at}",
            flush=True,
        )
        return html, cost

    production.feed.fetch_forebet_date = fetch_with_availability
