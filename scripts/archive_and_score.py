"""Archive pre-match predictions, ingest official HKJC results, and score models.

One latest pre-event snapshot is retained per HKJC front-end event id. Once
kickoff passes that prediction row is immutable. Results come from HKJC's own
matchResult GraphQL. Evaluation is descriptive only: RPS, multi-class Brier
score and log loss for independent probability models and no-vig market
benchmarks.
"""
from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from hkjc.scraper import HKJCFootball

HKT = ZoneInfo("Asia/Hong_Kong")
ROOT = Path(__file__).resolve().parent.parent
FOREBET = ROOT / "data" / "forebet_current.csv"
MODEL = ROOT / "data" / "model_current.csv"
FORM = ROOT / "data" / "form_current.csv"
BET365 = ROOT / "data" / "bet365_current.csv"
PRED_ARCHIVE = ROOT / "data" / "prediction_archive.csv"
RESULTS_ARCHIVE = ROOT / "data" / "results_archive.csv"
EVAL_CURRENT = ROOT / "data" / "evaluation_current.csv"
EVAL_SUMMARY = ROOT / "data" / "evaluation_summary.csv"

PRED_COLUMNS = [
    "hkjc_event_id", "kickoff_hkt", "captured_at_hkt", "league", "home", "away",
    "forebet_home", "forebet_draw", "forebet_away", "forebet_pick",
    "hkjc_home", "hkjc_draw", "hkjc_away", "opta_home", "opta_away",
    "bet365_home", "bet365_draw", "bet365_away",
    "dc_home", "dc_draw", "dc_away", "dc_xg_home", "dc_xg_away",
    "pi_home", "pi_draw", "pi_away", "pi_diff", "model_quality", "model_source",
    "form_home", "form_draw", "form_away", "form_xg_home", "form_xg_away",
    "form_quality", "form_source",
]
RESULT_COLUMNS = [
    "hkjc_event_id", "match_id", "kickoff_hkt", "tournament", "home", "away",
    "home_goals", "away_goals", "outcome", "payout_confirmed", "fetched_at_hkt",
]
EVAL_COLUMNS = [
    "hkjc_event_id", "kickoff_hkt", "home", "away", "home_goals", "away_goals", "outcome",
    "forebet_rps", "forebet_brier", "forebet_logloss",
    "dc_rps", "dc_brier", "dc_logloss",
    "pi_rps", "pi_brier", "pi_logloss",
    "form_rps", "form_brier", "form_logloss",
    "hkjc_market_rps", "hkjc_market_brier", "hkjc_market_logloss",
    "bet365_market_rps", "bet365_market_brier", "bet365_market_logloss",
    "model_source", "form_source",
]
SUMMARY_COLUMNS = ["as_of_hkt", "model", "settled_matches", "avg_rps", "avg_brier", "avg_logloss"]


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
    tmp.replace(path)


def parse_dt(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HKT)
    return dt.astimezone(HKT)


def as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def prob_triplet(values, percent: bool = False):
    nums = [as_float(v) for v in values]
    if any(v is None for v in nums):
        return None
    probs = [float(v) for v in nums]
    if percent or sum(probs) > 2.0:
        probs = [v / 100.0 for v in probs]
    total = sum(probs)
    if total <= 0:
        return None
    probs = [max(0.0, v / total) for v in probs]
    total = sum(probs)
    return [v / total for v in probs] if total else None


def market_probs(values):
    odds = [as_float(v) for v in values]
    if any(v is None or v <= 1.0 for v in odds):
        return None
    implied = [1.0 / v for v in odds]
    total = sum(implied)
    return [v / total for v in implied]


def outcome_vector(outcome: str):
    return {"H": [1.0, 0.0, 0.0], "D": [0.0, 1.0, 0.0], "A": [0.0, 0.0, 1.0]}.get(outcome)


def metrics(probs, outcome: str):
    actual = outcome_vector(outcome)
    if probs is None or actual is None:
        return ("", "", "")
    p = [min(1 - 1e-12, max(1e-12, float(v))) for v in probs]
    rps = 0.5 * ((p[0] - actual[0]) ** 2 + ((p[0] + p[1]) - (actual[0] + actual[1])) ** 2)
    brier = sum((p[i] - actual[i]) ** 2 for i in range(3)) / 3.0
    logloss = -math.log(p[actual.index(1.0)])
    return (f"{rps:.6f}", f"{brier:.6f}", f"{logloss:.6f}")


def build_prediction_rows(now: datetime) -> list[dict]:
    forebet = read_rows(FOREBET)
    models = {r.get("hkjc_event_id", ""): r for r in read_rows(MODEL) if r.get("hkjc_event_id")}
    forms = {r.get("hkjc_event_id", ""): r for r in read_rows(FORM) if r.get("hkjc_event_id")}
    markets = {r.get("hkjc_event_id", ""): r for r in read_rows(BET365) if r.get("hkjc_event_id")}
    out = []
    for f in forebet:
        event_id = f.get("hkjc_event_id", "")
        kickoff = parse_dt(f.get("hkjc_kickoff_hkt", ""))
        if not event_id or kickoff is None or now > kickoff:
            continue
        model = models.get(event_id, {})
        form = forms.get(event_id, {})
        market = markets.get(event_id, {})
        out.append({
            "hkjc_event_id": event_id,
            "kickoff_hkt": kickoff.isoformat(timespec="minutes"),
            "captured_at_hkt": now.replace(microsecond=0).isoformat(),
            "league": f.get("hkjc_league", ""),
            "home": f.get("hkjc_home_team", "") or f.get("home_team", ""),
            "away": f.get("hkjc_away_team", "") or f.get("away_team", ""),
            "forebet_home": f.get("prob_home", ""),
            "forebet_draw": f.get("prob_draw", ""),
            "forebet_away": f.get("prob_away", ""),
            "forebet_pick": f.get("prediction_1x2", ""),
            "hkjc_home": f.get("hkjc_had_home", ""),
            "hkjc_draw": f.get("hkjc_had_draw", ""),
            "hkjc_away": f.get("hkjc_had_away", ""),
            "opta_home": f.get("power_home", ""),
            "opta_away": f.get("power_away", ""),
            "bet365_home": market.get("bet365_home", ""),
            "bet365_draw": market.get("bet365_draw", ""),
            "bet365_away": market.get("bet365_away", ""),
            "dc_home": model.get("dc_prob_home", ""),
            "dc_draw": model.get("dc_prob_draw", ""),
            "dc_away": model.get("dc_prob_away", ""),
            "dc_xg_home": model.get("dc_xg_home", ""),
            "dc_xg_away": model.get("dc_xg_away", ""),
            "pi_home": model.get("pi_prob_home", ""),
            "pi_draw": model.get("pi_prob_draw", ""),
            "pi_away": model.get("pi_prob_away", ""),
            "pi_diff": model.get("pi_diff", ""),
            "model_quality": model.get("quality", ""),
            "model_source": model.get("model_source", ""),
            "form_home": form.get("form_prob_home", ""),
            "form_draw": form.get("form_prob_draw", ""),
            "form_away": form.get("form_prob_away", ""),
            "form_xg_home": form.get("form_xg_home", ""),
            "form_xg_away": form.get("form_xg_away", ""),
            "form_quality": form.get("quality", ""),
            "form_source": form.get("model_source", ""),
        })
    return out


def update_prediction_archive(now: datetime) -> int:
    existing = {r.get("hkjc_event_id", ""): r for r in read_rows(PRED_ARCHIVE) if r.get("hkjc_event_id")}
    changed = 0
    for row in build_prediction_rows(now):
        event_id = row["hkjc_event_id"]
        old = existing.get(event_id)
        old_time = parse_dt(old.get("captured_at_hkt", "")) if old else None
        new_time = parse_dt(row.get("captured_at_hkt", ""))
        if old is None or (new_time and (old_time is None or new_time > old_time)):
            existing[event_id] = row
            changed += 1
    rows = sorted(existing.values(), key=lambda r: (r.get("kickoff_hkt", ""), r.get("hkjc_event_id", "")))
    write_rows(PRED_ARCHIVE, PRED_COLUMNS, rows)
    return changed


def fetch_results(now: datetime) -> list[dict]:
    fb = HKJCFootball()
    start = (now.date() - timedelta(days=30)).isoformat()
    end = now.date().isoformat()
    raw = fb.fetch_results(start_date=start, end_date=end)
    fetched = now.replace(microsecond=0).isoformat()
    out = []
    for match in raw.get("matches") or []:
        ft = next((r for r in (match.get("results") or []) if r.get("resultType") == 1 and r.get("stageId") == 5), None)
        if not ft:
            continue
        hg, ag = ft.get("homeResult"), ft.get("awayResult")
        if not isinstance(hg, int) or not isinstance(ag, int) or hg < 0 or ag < 0:
            continue
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}
        tournament = match.get("tournament") or {}
        event_id = str(match.get("frontEndId") or "").strip()
        if not event_id:
            continue
        out.append({
            "hkjc_event_id": event_id,
            "match_id": str(match.get("id") or ""),
            "kickoff_hkt": str(match.get("kickOffTime") or ""),
            "tournament": str(tournament.get("code") or ""),
            "home": str(home.get("name_en") or home.get("name_ch") or ""),
            "away": str(away.get("name_en") or away.get("name_ch") or ""),
            "home_goals": hg,
            "away_goals": ag,
            "outcome": "H" if hg > ag else "A" if ag > hg else "D",
            "payout_confirmed": ft.get("payoutConfirmed", ""),
            "fetched_at_hkt": fetched,
        })
    return out


def stable_result(row: dict) -> tuple:
    return tuple(str(row.get(k, "")) for k in RESULT_COLUMNS if k != "fetched_at_hkt")


def update_results_archive(now: datetime) -> int:
    existing = {r.get("hkjc_event_id", ""): r for r in read_rows(RESULTS_ARCHIVE) if r.get("hkjc_event_id")}
    changed = 0
    for row in fetch_results(now):
        old = existing.get(row["hkjc_event_id"])
        if old is None or stable_result(old) != stable_result(row):
            existing[row["hkjc_event_id"]] = row
            changed += 1
    rows = sorted(existing.values(), key=lambda r: (r.get("kickoff_hkt", ""), r.get("hkjc_event_id", "")))
    write_rows(RESULTS_ARCHIVE, RESULT_COLUMNS, rows)
    return changed


def build_evaluation(now: datetime) -> tuple[int, int]:
    preds = {r.get("hkjc_event_id", ""): r for r in read_rows(PRED_ARCHIVE) if r.get("hkjc_event_id")}
    results = {r.get("hkjc_event_id", ""): r for r in read_rows(RESULTS_ARCHIVE) if r.get("hkjc_event_id")}
    evaluated = []
    for event_id, p in preds.items():
        result = results.get(event_id)
        if not result:
            continue
        outcome = result.get("outcome", "")
        forebet = metrics(prob_triplet([p.get("forebet_home"), p.get("forebet_draw"), p.get("forebet_away")], percent=True), outcome)
        dc = metrics(prob_triplet([p.get("dc_home"), p.get("dc_draw"), p.get("dc_away")]), outcome)
        pi = metrics(prob_triplet([p.get("pi_home"), p.get("pi_draw"), p.get("pi_away")]), outcome)
        form = metrics(prob_triplet([p.get("form_home"), p.get("form_draw"), p.get("form_away")]), outcome)
        hkjc = metrics(market_probs([p.get("hkjc_home"), p.get("hkjc_draw"), p.get("hkjc_away")]), outcome)
        bet365 = metrics(market_probs([p.get("bet365_home"), p.get("bet365_draw"), p.get("bet365_away")]), outcome)
        evaluated.append({
            "hkjc_event_id": event_id,
            "kickoff_hkt": p.get("kickoff_hkt", ""),
            "home": p.get("home", ""),
            "away": p.get("away", ""),
            "home_goals": result.get("home_goals", ""),
            "away_goals": result.get("away_goals", ""),
            "outcome": outcome,
            "forebet_rps": forebet[0], "forebet_brier": forebet[1], "forebet_logloss": forebet[2],
            "dc_rps": dc[0], "dc_brier": dc[1], "dc_logloss": dc[2],
            "pi_rps": pi[0], "pi_brier": pi[1], "pi_logloss": pi[2],
            "form_rps": form[0], "form_brier": form[1], "form_logloss": form[2],
            "hkjc_market_rps": hkjc[0], "hkjc_market_brier": hkjc[1], "hkjc_market_logloss": hkjc[2],
            "bet365_market_rps": bet365[0], "bet365_market_brier": bet365[1], "bet365_market_logloss": bet365[2],
            "model_source": p.get("model_source", ""),
            "form_source": p.get("form_source", ""),
        })
    evaluated.sort(key=lambda r: (r.get("kickoff_hkt", ""), r.get("hkjc_event_id", "")))
    write_rows(EVAL_CURRENT, EVAL_COLUMNS, evaluated)

    definitions = {
        "Forebet": ("forebet_rps", "forebet_brier", "forebet_logloss"),
        "Dixon-Coles": ("dc_rps", "dc_brier", "dc_logloss"),
        "Pi": ("pi_rps", "pi_brier", "pi_logloss"),
        "HKJC Team-Form Poisson": ("form_rps", "form_brier", "form_logloss"),
        "HKJC no-vig market": ("hkjc_market_rps", "hkjc_market_brier", "hkjc_market_logloss"),
        "Bet365 no-vig market": ("bet365_market_rps", "bet365_market_brier", "bet365_market_logloss"),
    }
    summary = []
    as_of = now.replace(microsecond=0).isoformat()
    scored_samples = 0
    for name, keys in definitions.items():
        usable = [r for r in evaluated if all(r.get(k) not in (None, "") for k in keys)]
        scored_samples += len(usable)
        if not usable:
            summary.append({"as_of_hkt": as_of, "model": name, "settled_matches": 0, "avg_rps": "", "avg_brier": "", "avg_logloss": ""})
            continue
        values = [[float(r[k]) for k in keys] for r in usable]
        summary.append({
            "as_of_hkt": as_of,
            "model": name,
            "settled_matches": len(usable),
            "avg_rps": f"{sum(v[0] for v in values)/len(values):.6f}",
            "avg_brier": f"{sum(v[1] for v in values)/len(values):.6f}",
            "avg_logloss": f"{sum(v[2] for v in values)/len(values):.6f}",
        })
    write_rows(EVAL_SUMMARY, SUMMARY_COLUMNS, summary)
    return len(evaluated), scored_samples


def main() -> int:
    now = datetime.now(HKT)
    prediction_updates = update_prediction_archive(now)
    result_updates = update_results_archive(now)
    evaluated, scored_samples = build_evaluation(now)
    print(
        f"EVALUATION prediction_updates={prediction_updates} result_updates={result_updates} "
        f"settled_prediction_rows={evaluated} scored_model_samples={scored_samples}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
