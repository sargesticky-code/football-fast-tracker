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

import forebet_unresolved_diagnostics as unresolved_diagnostics

HKT = ZoneInfo("Asia/Hong_Kong")
LIVESCORE_URL = "https://www.forebet.com/en/livescore"
_LIVESCORE_CACHE: str | None | bool = False
_AVAILABILITY: dict[str, dict[str, str]] = {}
_PREVIOUS_AVAILABILITY: dict[str, dict[str, str]] = {}
_PREVIOUS_LOADED = False

FIELDS = [
    "checked_at_hkt", "match_date", "kickoff_hkt", "hkjc_event_id", "league_zh",
    "home_en", "away_en", "state", "reason",
    "source_home_team", "source_away_team", "source_competition",
    "fixture_match_score", "identity_status", "identity_source",
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


def _asian_games_base(production, value: str) -> str:
    key = production.feed.normalize_team(str(value or ""))
    key = re.sub(r"\b(?:u23|am)\b$", "", key).strip()
    aliases = {
        "south korea": "korea republic",
        "north korea": "korea dpr",
        "uae": "united arab emirates",
    }
    return aliases.get(key, key)


def _asian_games_equivalent(production, source_name: str, canonical_name: str) -> bool:
    source_norm = production.feed.normalize_team(str(source_name or ""))
    canonical_norm = production.feed.normalize_team(str(canonical_name or ""))
    if not source_norm.endswith(" u23") or not canonical_norm.endswith(" am"):
        return False
    return _asian_games_base(production, source_norm) == _asian_games_base(
        production, canonical_norm
    )


def _nearest_competition(lines: list[str], home_index: int) -> str:
    """Best-effort livescore section label retained as audit context only."""
    for index in range(home_index - 1, max(-1, home_index - 18), -1):
        candidate = lines[index].strip()
        lower = candidate.casefold()
        if not candidate or len(candidate) > 140:
            continue
        if re.fullmatch(r"\d{1,2}:\d{2}", candidate):
            continue
        if lower.startswith(("image", "title:", "url source:", "markdown content:")):
            continue
        if ":" in candidate:
            return candidate
    return ""


def _fixture_evidence(
    production, body: str | None, targets: list[dict]
) -> dict[str, dict[str, str]]:
    """Return fixture-presence evidence without throwing away provider identity.

    Identity resolution is deliberately static-master-first:
    1) source competition + source team context master;
    2) globally safe verified source-team master;
    3) narrowly scoped cohort rules used only to discover new context rows;
    4) conservative similarity for genuinely unseen names.

    Once an alias/context has been learned, later runs therefore do a dictionary
    lookup rather than recomputing fuzzy identity.
    """
    if not body:
        return {}
    lines = [_clean_line(line) for line in body.splitlines() if line.strip()]
    lines = [line for line in lines if line]
    found: dict[str, dict[str, str]] = {}

    context_map = production.feed.forebet_context_map()
    global_master = production.feed.forebet_master_map()
    competition_map = production.feed.forebet_competition_map()

    def canonical_eq(left: str, right: str) -> bool:
        return (
            production.feed.normalize_team(str(left or ""))
            == production.feed.normalize_team(str(right or ""))
        )

    for target in targets:
        event_id = str(target.get("hkjc_event_id") or "").strip()
        home = str(target.get("home_en") or "").strip()
        away = str(target.get("away_en") or "").strip()
        target_comp = str(target.get("league_zh") or "").strip()
        if not event_id or not home or not away:
            continue

        candidates: list[dict[str, object]] = []
        for i, line in enumerate(lines):
            source_comp = _nearest_competition(lines, i)
            comp_key = production.feed.normalize_competition(source_comp)
            source_team_key = production.feed.normalize_team(line)
            mapped_comp = competition_map.get(comp_key, "")
            competition_compatible = (
                not mapped_comp
                or production.feed.normalize_competition(mapped_comp)
                == production.feed.normalize_competition(target_comp)
            )

            home_ctx = context_map.get((comp_key, source_team_key))
            static_context_home = bool(
                competition_compatible
                and home_ctx
                and canonical_eq(home_ctx[0], home)
                and (
                    not home_ctx[1]
                    or production.feed.normalize_competition(home_ctx[1])
                    == production.feed.normalize_competition(target_comp)
                )
            )
            home_global = global_master.get(source_team_key)
            static_global_home = bool(
                home_global and canonical_eq(home_global, home)
            )
            asian_games_home = (
                target_comp == "AMF"
                and "asian games" in source_comp.casefold()
                and _asian_games_equivalent(production, line, home)
            )

            if static_context_home:
                hs = 1.0
                home_path = "CONTEXT_MASTER"
            elif static_global_home:
                hs = 0.995
                home_path = "GLOBAL_MASTER"
            elif asian_games_home:
                hs = 1.0
                home_path = "ASIAN_GAMES_CONTEXT_DISCOVERY"
            else:
                hs = production.feed.team_score(line, home)
                home_path = "DISCOVERY"

            if hs < 0.68:
                continue

            for j in range(i + 1, min(len(lines), i + 6)):
                away_line = lines[j]
                away_team_key = production.feed.normalize_team(away_line)
                away_ctx = context_map.get((comp_key, away_team_key))
                static_context_away = bool(
                    competition_compatible
                    and away_ctx
                    and canonical_eq(away_ctx[0], away)
                    and (
                        not away_ctx[1]
                        or production.feed.normalize_competition(away_ctx[1])
                        == production.feed.normalize_competition(target_comp)
                    )
                )
                away_global = global_master.get(away_team_key)
                static_global_away = bool(
                    away_global and canonical_eq(away_global, away)
                )
                asian_games_away = (
                    asian_games_home
                    and _asian_games_equivalent(production, away_line, away)
                )

                if static_context_away:
                    aws = 1.0
                    away_path = "CONTEXT_MASTER"
                elif static_global_away:
                    aws = 0.995
                    away_path = "GLOBAL_MASTER"
                elif asian_games_away:
                    aws = 1.0
                    away_path = "ASIAN_GAMES_CONTEXT_DISCOVERY"
                else:
                    aws = production.feed.team_score(away_line, away)
                    away_path = "DISCOVERY"

                avg = (hs + aws) / 2
                if hs >= 0.68 and aws >= 0.68 and avg >= 0.76:
                    candidates.append({
                        "avg": avg,
                        "hs": hs,
                        "aws": aws,
                        "i": i,
                        "j": j,
                        "source_comp": source_comp,
                        "home_path": home_path,
                        "away_path": away_path,
                    })

        if not candidates:
            continue

        candidates.sort(key=lambda item: float(item["avg"]), reverse=True)
        top = candidates[0]
        best = float(top["avg"])
        hs = float(top["hs"])
        aws = float(top["aws"])
        i = int(top["i"])
        j = int(top["j"])
        source_comp = str(top["source_comp"])
        home_path = str(top["home_path"])
        away_path = str(top["away_path"])
        second = float(candidates[1]["avg"]) if len(candidates) > 1 else 0.0

        static_context_pair = (
            home_path == "CONTEXT_MASTER" and away_path == "CONTEXT_MASTER"
        )
        static_global_pair = (
            home_path in {"CONTEXT_MASTER", "GLOBAL_MASTER"}
            and away_path in {"CONTEXT_MASTER", "GLOBAL_MASTER"}
        )
        context_discovery_pair = (
            home_path == "ASIAN_GAMES_CONTEXT_DISCOVERY"
            and away_path == "ASIAN_GAMES_CONTEXT_DISCOVERY"
        )

        unique_margin = best - second
        discovery_verified = (
            best >= 0.94
            and hs >= 0.90
            and aws >= 0.90
            and (second < 0.88 or unique_margin >= 0.05)
        )

        if static_context_pair:
            identity_status = "CONTEXT_VERIFIED"
            identity_source = "FOREBET_STATIC_CONTEXT_MASTER"
            best = 1.0
        elif context_discovery_pair:
            identity_status = "CONTEXT_VERIFIED"
            identity_source = "FOREBET_LIVESCORE_ASIAN_GAMES_CONTEXT"
            best = 1.0
        elif static_global_pair:
            identity_status = "VERIFIED"
            identity_source = "FOREBET_STATIC_TEAM_MASTER"
        else:
            identity_status = "VERIFIED" if discovery_verified else "CANDIDATE"
            identity_source = "FOREBET_LIVESCORE"

        found[event_id] = {
            "source_home_team": lines[i],
            "source_away_team": lines[j],
            "source_competition": source_comp,
            "fixture_match_score": f"{best:.3f}",
            "identity_status": identity_status,
            "identity_source": identity_source,
        }
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
        fixture_evidence: dict[str, dict[str, str]] = {}
        if unresolved_targets:
            fixture_evidence = _fixture_evidence(
                production,
                _fetch_livescore(production),
                unresolved_targets,
            )
        fixture_ids = set(fixture_evidence)

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
                diagnosis = unresolved_diagnostics.get_diagnosis(event_id)
                reason = {
                    "SOURCE_UNAVAILABLE": "forebet_source_surface_unavailable",
                    "NO_SOURCE_ROWS": "no_forebet_source_rows_for_date",
                    "NO_CLOSE_FIXTURE_ON_FETCHED_MODEL_SURFACES": "forebet_fixture_absent_from_fetched_model_surfaces",
                    "SOURCE_SURFACE_ABSENT": "forebet_fixture_absent_from_fetched_model_surfaces",
                    "WEAK_NAME_CANDIDATE": "weak_forebet_name_candidate_review",
                    "ALIAS_NEAR_MISS": "forebet_alias_near_miss_review",
                    "PUBLISHED_WITHOUT_USABLE_MODEL": "forebet_fixture_published_without_usable_model",
                    "MATCH_POLICY_REVIEW": "forebet_match_policy_review",
                }.get(diagnosis, "not_resolved_on_forebet_prediction_or_livescore_surfaces")
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
                "source_home_team": str(
                    fixture_evidence.get(event_id, {}).get("source_home_team")
                    or previous.get(event_id, {}).get("source_home_team")
                    or ""
                ),
                "source_away_team": str(
                    fixture_evidence.get(event_id, {}).get("source_away_team")
                    or previous.get(event_id, {}).get("source_away_team")
                    or ""
                ),
                "source_competition": str(
                    fixture_evidence.get(event_id, {}).get("source_competition")
                    or previous.get(event_id, {}).get("source_competition")
                    or ""
                ),
                "fixture_match_score": str(
                    fixture_evidence.get(event_id, {}).get("fixture_match_score")
                    or previous.get(event_id, {}).get("fixture_match_score")
                    or ""
                ),
                "identity_status": str(
                    fixture_evidence.get(event_id, {}).get("identity_status")
                    or previous.get(event_id, {}).get("identity_status")
                    or ""
                ),
                "identity_source": str(
                    fixture_evidence.get(event_id, {}).get("identity_source")
                    or previous.get(event_id, {}).get("identity_source")
                    or ""
                ),
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
