"""Build the player-first match-path feature feed for Fast Tracker.

This intentionally does NOT invent segment probabilities before calibration.
It combines current evidence into a per-segment scenario feature table so the
live edge engine has a stable contract now and can activate calibrated
probabilities later without redesigning the pipeline.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
HKJC = ROOT / "data" / "hkjc_current.csv"
CONTEXT = ROOT / "data" / "prematch_context_current.csv"
FOREBET = ROOT / "data" / "forebet_current.csv"
MODEL = ROOT / "data" / "model_current.csv"
PLAYERS = ROOT / "data" / "player_profile_registry.csv"
STYLES = ROOT / "data" / "team_style_registry.csv"
OUT = ROOT / "data" / "match_scenario_current.csv"

HKT = ZoneInfo("Asia/Hong_Kong")
SEGMENTS = ("0-15", "16-30", "31-HT", "46-60", "61-75", "76-FT")
LOOKAHEAD_HOURS = 36

COLUMNS = [
    "fetched_at_hkt", "hkjc_event_id", "kickoff_hkt", "league",
    "home", "away", "segment",
    "model_hda_consensus", "forebet_hda", "dc_hda", "pi_hda",
    "forebet_ou25", "forebet_corner",
    "macro_control_side", "control_basis",
    "home_possession_baseline", "away_possession_baseline",
    "home_manager", "away_manager",
    "home_lineup_status", "home_player_profiles", "away_player_profiles",
    "home_recent_minutes", "away_recent_minutes",
    "home_recent_goals", "away_recent_goals",
    "home_recent_assists", "away_recent_assists",
    "home_injury_profiles", "away_injury_profiles",
    "context_coverage_score",
    "p_home_goal_segment", "p_away_goal_segment", "p_no_goal_segment",
    "expected_home_corners_segment", "expected_away_corners_segment",
    "expected_score_state",
    "segment_prediction_status", "notes",
]


def clean(v):
    return "" if v is None else str(v).strip()


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_csv(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(rows):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in COLUMNS})
    tmp.replace(OUT)


def parse_dt(v):
    s = clean(v)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HKT)
    return dt.astimezone(HKT)


def argmax_hda(h, d, a):
    vals = [num(h), num(d), num(a)]
    if any(v is None for v in vals):
        return ""
    m = max(vals)
    if vals.count(m) > 1:
        return "TIE"
    return ("H", "D", "A")[vals.index(m)]


def forebet_dir(row):
    v = clean(row.get("prediction_1x2")).upper()
    if v in ("1", "H", "HOME"):
        return "H"
    if v in ("X", "D", "DRAW"):
        return "D"
    if v in ("2", "A", "AWAY"):
        return "A"
    return argmax_hda(row.get("prob_home"), row.get("prob_draw"), row.get("prob_away"))


def consensus(values):
    vals = [v for v in values if v in ("H", "D", "A")]
    if not vals:
        return ""
    counts = Counter(vals)
    top, n = counts.most_common(1)[0]
    if list(counts.values()).count(n) > 1:
        return "CONFLICT"
    return top if n >= 2 or len(vals) == 1 else "CONFLICT"


def player_aggregate(rows):
    out = {
        "profiles": len(rows),
        "minutes": 0.0,
        "goals": 0.0,
        "assists": 0.0,
        "injuries": 0,
    }
    for r in rows:
        out["minutes"] += num(r.get("recent_minutes")) or 0.0
        out["goals"] += num(r.get("recent_goals")) or 0.0
        out["assists"] += num(r.get("recent_assists")) or 0.0
        if clean(r.get("injury_status")):
            out["injuries"] += 1
    return out


def possession(row):
    v = num((row or {}).get("average_possession"))
    return v if v is not None and 20 <= v <= 80 else None


def macro_control(model_consensus, hp, ap):
    style_side = ""
    if hp is not None and ap is not None:
        diff = hp - ap
        if diff >= 4:
            style_side = "H"
        elif diff <= -4:
            style_side = "A"
        else:
            style_side = "EVEN"

    directional_model = model_consensus if model_consensus in ("H", "A") else ""
    if style_side in ("H", "A") and directional_model:
        if style_side == directional_model:
            return style_side, "MODEL+CURRENT_POSSESSION_STYLE"
        return "CONFLICT", "MODEL_VS_CURRENT_POSSESSION_STYLE"
    if style_side in ("H", "A"):
        return style_side, "CURRENT_POSSESSION_STYLE"
    if directional_model:
        return directional_model, "HDA_MODEL_CONSENSUS"
    if style_side == "EVEN" or model_consensus == "D":
        return "EVEN", "BALANCED_CURRENT_EVIDENCE"
    return "UNKNOWN", "INSUFFICIENT_CURRENT_EVIDENCE"


def coverage(ctx, fb, model, hstyle, astyle, hp, ap):
    score = 0
    if clean(ctx.get("fotmob_match_id")):
        score += 10
    if clean(ctx.get("home_manager")):
        score += 10
    if clean(ctx.get("away_manager")):
        score += 10
    if possession(hstyle) is not None:
        score += 10
    if possession(astyle) is not None:
        score += 10
    if hp["profiles"] >= 3:
        score += 10
    if ap["profiles"] >= 3:
        score += 10
    if model and clean(model.get("quality")) == "MODELED":
        score += 15
    if fb:
        score += 10
    if clean(ctx.get("lineup_status")).upper() in ("CONFIRMED", "PREDICTED", "AVAILABLE"):
        score += 5
    return score


def main():
    now = datetime.now(HKT).replace(microsecond=0)
    fetched = now.isoformat()
    upper = now + timedelta(hours=LOOKAHEAD_HOURS)

    # HKJC is the canonical scenario universe. Prematch/FotMob context is an
    # enrichment layer only, so an enrichment workflow that is one cycle late
    # can never make a live match lose its pre-match scenario.
    context_by_id = {
        clean(r.get("hkjc_event_id")): r
        for r in read_csv(CONTEXT)
        if clean(r.get("hkjc_event_id"))
    }
    previous_by_event = {}
    for r in read_csv(OUT):
        eid = clean(r.get("hkjc_event_id"))
        if eid and eid not in previous_by_event:
            previous_by_event[eid] = r

    context = []
    ended_tokens = ("MATCHENDED", "INPLAYMATCHENDED", "ENDED", "CANCEL", "VOID", "ABANDON")
    for h in read_csv(HKJC):
        eid = clean(h.get("hkjc_event_id"))
        kick = parse_dt(h.get("kickoff_hkt"))
        if not eid or kick is None or not (now - timedelta(hours=4) <= kick <= upper):
            continue
        status = clean(h.get("status")).upper()
        in_play = clean(h.get("in_play")).lower() in ("1", "true", "yes")
        if any(token in status for token in ended_tokens) and not in_play:
            continue

        enriched = dict(context_by_id.get(eid) or {})
        previous = previous_by_event.get(eid) or {}
        base = {
            "hkjc_event_id": eid,
            "kickoff_hkt": kick.isoformat(timespec="minutes"),
            "league": clean(h.get("tournament")),
            "home": clean(h.get("home_en")),
            "away": clean(h.get("away_en")),
        }
        base.update({k: v for k, v in enriched.items() if clean(v)})

        # Preserve slow-changing last-good context if the current enrichment
        # pass could not resolve the live fixture after kickoff.
        for key in (
            "fotmob_match_id", "fotmob_home_id", "fotmob_away_id",
            "home_manager", "away_manager", "home_formation",
            "away_formation", "lineup_status",
        ):
            if not clean(base.get(key)) and clean(previous.get(key)):
                base[key] = previous.get(key)

        context.append(base)

    fb_by_id = {clean(r.get("hkjc_event_id")): r for r in read_csv(FOREBET) if clean(r.get("hkjc_event_id"))}
    model_by_id = {clean(r.get("hkjc_event_id")): r for r in read_csv(MODEL) if clean(r.get("hkjc_event_id"))}
    styles = {clean(r.get("team_id")): r for r in read_csv(STYLES) if clean(r.get("team_id"))}

    players = defaultdict(list)
    for r in read_csv(PLAYERS):
        tid = clean(r.get("team_id"))
        if tid:
            players[tid].append(r)

    out = []
    ready_context = 0
    for ctx in context:
        eid = clean(ctx.get("hkjc_event_id"))
        fb = fb_by_id.get(eid)
        model = model_by_id.get(eid)

        fdir = forebet_dir(fb) if fb else ""
        dcdir = ""
        pidir = ""
        if model and clean(model.get("quality")) == "MODELED":
            dcdir = argmax_hda(model.get("dc_prob_home"), model.get("dc_prob_draw"), model.get("dc_prob_away"))
            pidir = argmax_hda(model.get("pi_prob_home"), model.get("pi_prob_draw"), model.get("pi_prob_away"))
        hda = consensus((fdir, dcdir, pidir))

        hid = clean(ctx.get("fotmob_home_id"))
        aid = clean(ctx.get("fotmob_away_id"))
        hp = player_aggregate(players.get(hid, []))
        ap = player_aggregate(players.get(aid, []))
        hs = styles.get(hid)
        a_s = styles.get(aid)
        hposs = possession(hs)
        aposs = possession(a_s)
        control, basis = macro_control(hda, hposs, aposs)
        cov = coverage(ctx, fb, model, hs, a_s, hp, ap)
        if cov >= 60:
            ready_context += 1

        notes = []
        if clean(ctx.get("lineup_status")).upper() not in ("CONFIRMED", "PREDICTED", "AVAILABLE"):
            notes.append("lineup_not_confirmed")
        if hp["profiles"] < 3 or ap["profiles"] < 3:
            notes.append("player_profile_coverage_low")
        if not model or clean(model.get("quality")) != "MODELED":
            notes.append("dc_pi_unavailable")
        notes.append("segment_probabilities_wait_for_recent_live_calibration")

        for segment in SEGMENTS:
            out.append({
                "fetched_at_hkt": fetched,
                "hkjc_event_id": eid,
                "kickoff_hkt": clean(ctx.get("kickoff_hkt")),
                "league": clean(ctx.get("league")),
                "home": clean(ctx.get("home")),
                "away": clean(ctx.get("away")),
                "segment": segment,
                "model_hda_consensus": hda,
                "forebet_hda": fdir,
                "dc_hda": dcdir,
                "pi_hda": pidir,
                "forebet_ou25": clean((fb or {}).get("prediction_ou25")),
                "forebet_corner": clean((fb or {}).get("corner_prediction")),
                "macro_control_side": control,
                "control_basis": basis,
                "home_possession_baseline": "" if hposs is None else f"{hposs:.1f}",
                "away_possession_baseline": "" if aposs is None else f"{aposs:.1f}",
                "home_manager": clean(ctx.get("home_manager")),
                "away_manager": clean(ctx.get("away_manager")),
                "home_lineup_status": clean(ctx.get("lineup_status")),
                "home_player_profiles": hp["profiles"],
                "away_player_profiles": ap["profiles"],
                "home_recent_minutes": f"{hp['minutes']:.1f}",
                "away_recent_minutes": f"{ap['minutes']:.1f}",
                "home_recent_goals": f"{hp['goals']:.1f}",
                "away_recent_goals": f"{ap['goals']:.1f}",
                "home_recent_assists": f"{hp['assists']:.1f}",
                "away_recent_assists": f"{ap['assists']:.1f}",
                "home_injury_profiles": hp["injuries"],
                "away_injury_profiles": ap["injuries"],
                "context_coverage_score": cov,
                "segment_prediction_status": "CALIBRATING",
                "notes": ";".join(notes),
            })

    write_csv(out)
    print(
        f"SCENARIO_FEATURES matches={len(context)} rows={len(out)} "
        f"context_score_60plus={ready_context} status=CALIBRATING"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
