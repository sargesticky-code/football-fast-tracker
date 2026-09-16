"""Restore last-known Forebet models for still-active HKJC fixtures.

This is a generic resilience layer, not a league/event exception.  A free Jina
refresh may legitimately be partial; if an HKJC event is still in today's target
universe and we previously captured a valid Forebet model for the same FBxxxx,
carry that model back into forebet_current.csv.  Current HKJC identity/odds are
refreshed from hkjc_targets.csv while the old Forebet capture timestamp remains,
so model age stays observable.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENT = ROOT / "data" / "forebet_current.csv"
ARCHIVE = ROOT / "data" / "forebet_archive.csv"
TARGETS = ROOT / "data" / "hkjc_targets.csv"


def clean(value) -> str:
    return (value or "").strip()


def read(path: Path):
    if not path.exists():
        return [], []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        r = csv.DictReader(fh)
        return list(r), list(r.fieldnames or [])


def forebet_date(kickoff_hkt: str) -> str:
    value = clean(kickoff_hkt)
    try:
        dt = datetime.strptime(value[:16], "%Y-%m-%d %H:%M")
        return (dt - timedelta(hours=8)).date().isoformat()
    except Exception:
        return value[:10]


def archive_to_current(a: dict[str, str], t: dict[str, str]) -> dict[str, str]:
    kickoff = clean(t.get("kickoff_hkt")) or clean(a.get("hkjc_kickoff_hkt"))
    return {
        "fetched_at_hkt": clean(a.get("captured_at_hkt")),
        "match_date": forebet_date(kickoff),
        "kickoff_text": kickoff,
        "league_short": clean(t.get("league_code")) or clean(t.get("league_zh")) or clean(a.get("hkjc_league")),
        "home_team": clean(a.get("hkjc_home_team")) or clean(t.get("home_en")),
        "away_team": clean(a.get("hkjc_away_team")) or clean(t.get("away_en")),
        "prob_home": clean(a.get("prob_home")),
        "prob_draw": clean(a.get("prob_draw")),
        "prob_away": clean(a.get("prob_away")),
        "prediction_1x2": clean(a.get("prediction_1x2")),
        "predicted_score": clean(a.get("predicted_score")),
        "avg_goals": clean(a.get("avg_goals")),
        "odds_home": "", "odds_draw": "", "odds_away": "",
        "prediction_ou25": clean(a.get("prediction_ou25")),
        "prob_over25": clean(a.get("prob_over25")),
        "prob_under25": clean(a.get("prob_under25")),
        "odds_over25": "", "odds_under25": "",
        "hkjc_event_id": clean(t.get("hkjc_event_id")) or clean(a.get("hkjc_event_id")),
        "hkjc_league": clean(t.get("league_zh")) or clean(a.get("hkjc_league")),
        "hkjc_home_team": clean(t.get("home_en")) or clean(a.get("hkjc_home_team")),
        "hkjc_away_team": clean(t.get("away_en")) or clean(a.get("hkjc_away_team")),
        "hkjc_home_zh": clean(t.get("home_zh")) or clean(a.get("hkjc_home_zh")),
        "hkjc_away_zh": clean(t.get("away_zh")) or clean(a.get("hkjc_away_zh")),
        "hkjc_kickoff_hkt": kickoff,
        "hkjc_had_home": clean(t.get("had_home")),
        "hkjc_had_draw": clean(t.get("had_draw")),
        "hkjc_had_away": clean(t.get("had_away")),
        "match_score": "",
        "power_home": clean(a.get("power_home")),
        "power_away": clean(a.get("power_away")),
        "power_home_name": "", "power_away_name": "",
        "power_source": clean(a.get("power_source")),
        "power_updated": clean(a.get("power_updated")),
        "power_home_match": "", "power_away_match": "",
        "ou_predicted_score": clean(a.get("ou_predicted_score")),
        "corner_prediction": clean(a.get("corner_prediction")),
        "corner_prob_under95": clean(a.get("corner_prob_under95")),
        "corner_prob_over95": clean(a.get("corner_prob_over95")),
        "corner_predicted_score": clean(a.get("corner_predicted_score")),
        "avg_corners": clean(a.get("avg_corners")),
        "forebet_detail_url": clean(a.get("forebet_detail_url")),
    }


def main() -> int:
    current, current_fields = read(CURRENT)
    archive, _ = read(ARCHIVE)
    targets, _ = read(TARGETS)
    if not current_fields or not targets:
        raise SystemExit("missing current schema or HKJC targets")

    current_by_id = {clean(r.get("hkjc_event_id")): r for r in current if clean(r.get("hkjc_event_id"))}
    archive_by_id = {clean(r.get("hkjc_event_id")): r for r in archive if clean(r.get("hkjc_event_id"))}
    target_by_id = {clean(r.get("hkjc_event_id")): r for r in targets if clean(r.get("hkjc_event_id"))}

    restored = 0
    for event_id, target in target_by_id.items():
        if event_id in current_by_id:
            continue
        old = archive_by_id.get(event_id)
        if not old or not all(clean(old.get(k)) for k in ("prob_home", "prob_draw", "prob_away")):
            continue
        current_by_id[event_id] = archive_to_current(old, target)
        restored += 1

    fields = list(current_fields)
    for field in (
        "ou_predicted_score", "corner_prediction", "corner_prob_under95",
        "corner_prob_over95", "corner_predicted_score", "avg_corners",
        "forebet_detail_url",
    ):
        if field not in fields:
            fields.append(field)

    rows = sorted(current_by_id.values(), key=lambda r: (clean(r.get("hkjc_kickoff_hkt")), clean(r.get("hkjc_event_id"))))
    tmp = CURRENT.with_suffix(".restore.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows({k: row.get(k, "") for k in fields} for row in rows)
    tmp.replace(CURRENT)

    print(
        f"FOREBET_ARCHIVE_RESTORE restored={restored} current={len(rows)} "
        f"active_targets={len(target_by_id)} archive={len(archive_by_id)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
