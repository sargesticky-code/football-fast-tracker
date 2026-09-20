"""Explain why active HKJC fixtures remain unresolved after Forebet recovery.

This module never changes matching decisions or invents models.  It wraps the
fully recovered Forebet HTML and, for every HKJC target that still has no usable
1X2 model, records the nearest source fixture by the same production team-name
scoring policy.

The purpose is operational: future gaps can be separated into provider/source
absence versus a likely alias/name near-miss without ad-hoc manual guessing.
"""
from __future__ import annotations


DIAGNOSTICS: dict[str, str] = {}


def get_diagnosis(event_id: str) -> str:
    return DIAGNOSTICS.get(str(event_id or "").strip(), "")


def _usable_model_ids(production, html: str | None, match_date: str, targets: list[dict]) -> set[str]:
    ids: set[str] = set()
    if not html:
        return ids
    for row in production.feed.parse_forebet_rows(html, match_date):
        probs = (row.get("prob_home"), row.get("prob_draw"), row.get("prob_away"))
        if not all(isinstance(value, (int, float)) for value in probs):
            continue
        selected = production._original_attach(row, targets)
        if selected is None:
            continue
        event_id = str(selected.get("hkjc_event_id") or "").strip()
        if event_id:
            ids.add(event_id)
    return ids


def _classification(home_score: float, away_score: float, average: float, has_probs: bool) -> str:
    if home_score >= 0.68 and away_score >= 0.68 and average >= 0.76:
        return "PUBLISHED_WITHOUT_USABLE_MODEL" if not has_probs else "MATCH_POLICY_REVIEW"
    if average >= 0.65 and max(home_score, away_score) >= 0.80:
        return "ALIAS_NEAR_MISS"
    if average >= 0.50:
        return "WEAK_NAME_CANDIDATE"
    return "NO_CLOSE_FIXTURE_ON_FETCHED_MODEL_SURFACES"


def install(production) -> None:
    original_fetch = production.feed.fetch_forebet_date

    def fetch_with_diagnostics(match_date: str):
        html, cost = original_fetch(match_date)
        targets = [
            target for target in production._ACTIVE_TARGETS
            if str(target.get("match_date") or "") == match_date
        ]
        if not targets:
            return html, cost
        if not html:
            for target in targets:
                event_id = str(target.get("hkjc_event_id") or "").strip()
                if event_id:
                    DIAGNOSTICS[event_id] = "SOURCE_UNAVAILABLE"
            return html, cost

        rows = production.feed.parse_forebet_rows(html, match_date)
        model_ids = _usable_model_ids(production, html, match_date, targets)
        missing = [
            target for target in targets
            if str(target.get("hkjc_event_id") or "").strip() not in model_ids
        ]

        for target in missing:
            event_id = str(target.get("hkjc_event_id") or "").strip()
            best = None
            for row in rows:
                home_score = production.feed.team_score(
                    str(row.get("home_team") or ""), str(target.get("home_en") or "")
                )
                away_score = production.feed.team_score(
                    str(row.get("away_team") or ""), str(target.get("away_en") or "")
                )
                average = (home_score + away_score) / 2
                if best is None or average > best[0]:
                    probs = (row.get("prob_home"), row.get("prob_draw"), row.get("prob_away"))
                    has_probs = all(isinstance(value, (int, float)) for value in probs)
                    best = (average, home_score, away_score, has_probs, row)

            if best is None:
                DIAGNOSTICS[event_id] = "NO_SOURCE_ROWS"
                print(
                    f"FOREBET_UNRESOLVED_DIAG event={event_id} diagnosis=NO_SOURCE_ROWS "
                    f"fixture={target.get('home_en','')} vs {target.get('away_en','')}",
                    flush=True,
                )
                continue

            average, home_score, away_score, has_probs, row = best
            diagnosis = _classification(home_score, away_score, average, has_probs)
            DIAGNOSTICS[event_id] = diagnosis
            print(
                f"FOREBET_UNRESOLVED_DIAG event={event_id} diagnosis={diagnosis} "
                f"target={target.get('home_en','')} vs {target.get('away_en','')} "
                f"nearest={row.get('home_team','')} vs {row.get('away_team','')} "
                f"hs={home_score:.3f} aws={away_score:.3f} avg={average:.3f} "
                f"probs={int(has_probs)}",
                flush=True,
            )

        print(
            f"FOREBET_UNRESOLVED_DIAGNOSTICS date={match_date} "
            f"targets={len(targets)} models={len(model_ids)} unresolved={len(missing)} rows={len(rows)}",
            flush=True,
        )
        return html, cost

    production.feed.fetch_forebet_date = fetch_with_diagnostics
