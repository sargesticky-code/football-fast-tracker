"""Normalize direct HKJC GraphQL output into stable Fast Tracker CSV feeds.

Input files are produced by sososo829/hkjc-football-scraper. The direct HKJC
feed is authoritative for which fixtures are actually offered and for current
HAD prices. FBxxxx front-end ids are retained as the canonical cross-source
match key used by Fast Tracker.

The modelling target universe deliberately survives kickoff for a bounded
period. This keeps Forebet recovery aligned with the Fast Tracker LIVE window:
a match remains eligible until HKJC reports a terminal state or the configured
post-kickoff retention window expires. No competition-specific exceptions are
required.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")
ROOT = Path(__file__).resolve().parent.parent
CURRENT_OUT = ROOT / "data" / "hkjc_current.csv"
TARGET_OUT = ROOT / "data" / "hkjc_targets.csv"

CURRENT_COLUMNS = [
    "fetched_at_hkt", "match_id", "hkjc_event_id", "kickoff_hkt", "status",
    "tournament", "home_en", "away_en", "home_zh", "away_zh", "pools",
    "had_home", "had_draw", "had_away", "pool_status", "in_play", "selling",
    "odds_updated_at",
]
TARGET_COLUMNS = [
    "fetched_at_hkt", "match_date", "kickoff_hkt", "hkjc_event_id", "league_zh",
    "home_zh", "away_zh", "home_en", "away_en", "had_home", "had_draw",
    "had_away", "mapping_source", "forebet_state", "forebet_reason",
    "forebet_checked_at",
]

TERMINAL_STATUS_MARKERS = (
    "ENDED", "FINISHED", "FULLTIME", "FULL_TIME", "RESULT", "CLOSED",
    "CANCEL", "POSTPON", "ABANDON",
)


def _load_rows(path: Path, preferred: tuple[str, ...]) -> list[dict]:
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    if isinstance(obj, dict):
        for key in preferred:
            value = obj.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    raise ValueError(f"unsupported JSON shape in {path}")


def _parse_dt(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HKT)
    return dt.astimezone(HKT)


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _terminal_status(status: str) -> bool:
    value = (status or "").upper().strip()
    if value in {"FT", "AET", "PEN"}:
        return True
    return any(marker in value for marker in TERMINAL_STATUS_MARKERS)


def _previous_labels() -> dict[str, dict[str, str]]:
    if not TARGET_OUT.exists():
        return {}
    try:
        with TARGET_OUT.open(encoding="utf-8-sig", newline="") as fh:
            return {
                (r.get("hkjc_event_id") or "").strip(): r
                for r in csv.DictReader(fh)
                if (r.get("hkjc_event_id") or "").strip()
            }
    except Exception:
        return {}


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", required=True)
    ap.add_argument("--had", required=True)
    ap.add_argument("--horizon-hours", type=float, default=36.0)
    ap.add_argument("--live-retain-minutes", type=float, default=150.0)
    args = ap.parse_args()

    match_rows = _load_rows(Path(args.matches), ("matches", "data"))
    had_rows = _load_rows(Path(args.had), ("odds", "data"))
    if not match_rows:
        raise SystemExit("HKJC direct source returned zero matches")
    if not had_rows:
        raise SystemExit("HKJC direct source returned zero HAD rows")

    previous = _previous_labels()
    fetched = datetime.now(HKT).replace(microsecond=0)
    fetched_text = fetched.isoformat()

    # Aggregate main-line HAD selections into one record per FBxxxx match.
    odds_by_event: dict[str, dict] = {}
    for row in had_rows:
        if str(row.get("odds_type", "")).upper() != "HAD":
            continue
        if "main_line" in row and not _truthy(row.get("main_line")):
            continue
        if str(row.get("comb_status", "")).upper() not in {"", "AVAILABLE"}:
            continue
        event_id = (row.get("front_end_id") or "").strip()
        selection = str(row.get("selection") or "").upper().strip()
        if not event_id or selection not in {"H", "D", "A"}:
            continue
        rec = odds_by_event.setdefault(event_id, {
            "home_zh": (row.get("home_ch") or "").strip(),
            "away_zh": (row.get("away_ch") or "").strip(),
            "pool_status": (row.get("pool_status") or "").strip(),
            "in_play": bool(row.get("in_play")),
            "odds_updated_at": (row.get("updated_at") or "").strip(),
        })
        try:
            rec[f"had_{'draw' if selection == 'D' else 'home' if selection == 'H' else 'away'}"] = float(row.get("odds"))
        except (TypeError, ValueError):
            pass
        if row.get("home_ch"):
            rec["home_zh"] = str(row.get("home_ch")).strip()
        if row.get("away_ch"):
            rec["away_zh"] = str(row.get("away_ch")).strip()
        if row.get("pool_status"):
            rec["pool_status"] = str(row.get("pool_status")).strip()
        if row.get("updated_at"):
            rec["odds_updated_at"] = str(row.get("updated_at")).strip()
        rec["in_play"] = rec.get("in_play", False) or bool(row.get("in_play"))

    current: list[dict] = []
    targets: list[dict] = []
    now = datetime.now(HKT)
    horizon = now + timedelta(hours=args.horizon_hours)
    live_floor = now - timedelta(minutes=args.live_retain_minutes)
    retained_live = 0

    for m in match_rows:
        event_id = (m.get("front_end_id") or "").strip()
        if not event_id:
            continue
        kickoff = _parse_dt(str(m.get("kick_off") or ""))
        if kickoff is None:
            continue

        odds = odds_by_event.get(event_id, {})
        triplet = all(odds.get(k) not in (None, "") for k in ("had_home", "had_draw", "had_away"))
        pool_status = str(odds.get("pool_status") or "").upper()
        selling = triplet and pool_status in {"SELLINGSTARTED", ""}
        status = str(m.get("status") or "").upper().strip()
        old = previous.get(event_id, {})

        home_en = (m.get("home") or "").strip()
        away_en = (m.get("away") or "").strip()
        home_zh = (odds.get("home_zh") or old.get("home_zh") or home_en).strip()
        away_zh = (odds.get("away_zh") or old.get("away_zh") or away_en).strip()
        tournament = (m.get("tournament") or "").strip()
        league_label = (old.get("league_zh") or tournament).strip()

        current.append({
            "fetched_at_hkt": fetched_text,
            "match_id": m.get("match_id", ""),
            "hkjc_event_id": event_id,
            "kickoff_hkt": kickoff.isoformat(timespec="minutes"),
            "status": status,
            "tournament": tournament,
            "home_en": home_en,
            "away_en": away_en,
            "home_zh": home_zh,
            "away_zh": away_zh,
            "pools": m.get("pools", ""),
            "had_home": odds.get("had_home", ""),
            "had_draw": odds.get("had_draw", ""),
            "had_away": odds.get("had_away", ""),
            "pool_status": odds.get("pool_status", ""),
            "in_play": 1 if odds.get("in_play") else 0,
            "selling": 1 if selling else 0,
            "odds_updated_at": odds.get("odds_updated_at", ""),
        })

        # Preserve the most recent pre-match HAD triplet while a match is live.
        # HKJC often stops exposing a selling HAD line at kickoff, but Forebet
        # recovery still needs the fixture identity during Fast Tracker's LIVE
        # window. Current odds always take precedence over the retained snapshot.
        target_had_home = odds.get("had_home", "") or old.get("had_home", "")
        target_had_draw = odds.get("had_draw", "") or old.get("had_draw", "")
        target_had_away = odds.get("had_away", "") or old.get("had_away", "")
        target_triplet = all(v not in (None, "") for v in (target_had_home, target_had_draw, target_had_away))

        if kickoff > horizon or _terminal_status(status) or not target_triplet:
            continue

        preevent_eligible = status == "PREEVENT" and selling and kickoff >= live_floor
        live_eligible = live_floor <= kickoff <= now and status != "PREEVENT"
        # Also tolerate a stale PREEVENT status immediately after kickoff; the
        # time window is authoritative and matches the Sheet's 150-minute cap.
        stale_preevent_live = live_floor <= kickoff <= now and status == "PREEVENT"

        if not (preevent_eligible or live_eligible or stale_preevent_live):
            continue
        if kickoff <= now:
            retained_live += 1

        targets.append({
            "fetched_at_hkt": fetched_text,
            "match_date": kickoff.date().isoformat(),
            "kickoff_hkt": kickoff.strftime("%Y-%m-%d %H:%M"),
            "hkjc_event_id": event_id,
            "league_zh": league_label,
            "home_zh": home_zh,
            "away_zh": away_zh,
            "home_en": home_en,
            "away_en": away_en,
            "had_home": target_had_home,
            "had_draw": target_had_draw,
            "had_away": target_had_away,
            "mapping_source": "HKJC GraphQL",
            # Forebet owns these fields. Hourly HKJC refreshes preserve the
            # last classification until the next Forebet run checks it again.
            "forebet_state": old.get("forebet_state", ""),
            "forebet_reason": old.get("forebet_reason", ""),
            "forebet_checked_at": old.get("forebet_checked_at", ""),
        })

    current.sort(key=lambda r: (r["kickoff_hkt"], r["hkjc_event_id"]))
    targets.sort(key=lambda r: (r["kickoff_hkt"], r["hkjc_event_id"]))
    _write_csv(CURRENT_OUT, CURRENT_COLUMNS, current)
    _write_csv(TARGET_OUT, TARGET_COLUMNS, targets)

    print(
        f"HKJC_DIRECT matches={len(match_rows)} had_rows={len(had_rows)} "
        f"current={len(current)} targets={len(targets)} retained_live={retained_live} "
        f"horizon_h={args.horizon_hours:g} live_retain_min={args.live_retain_minutes:g}"
    )
    if not current:
        raise SystemExit("HKJC normalization produced zero current rows")
    if not targets:
        raise SystemExit("HKJC normalization produced zero active model targets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
