"""Normalize direct HKJC GraphQL output into stable Fast Tracker CSV feeds.

Input files are produced by sososo829/hkjc-football-scraper.  The direct HKJC
feed is authoritative for which fixtures are actually offered and for current
HAD prices.  FBxxxx front-end ids are retained as the canonical cross-source
match key used by Fast Tracker.
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
    "had_away", "mapping_source",
]


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
        # Keep the newest labels/status seen in the response.
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

        # Forebet gate is pre-match only. Keep only currently offered HAD matches
        # in the current modelling horizon. Finished/live rows remain in CURRENT.
        if status != "PREEVENT" or not selling:
            continue
        if kickoff < now - timedelta(minutes=5) or kickoff > horizon:
            continue
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
            "had_home": odds.get("had_home", ""),
            "had_draw": odds.get("had_draw", ""),
            "had_away": odds.get("had_away", ""),
            "mapping_source": "HKJC GraphQL",
        })

    current.sort(key=lambda r: (r["kickoff_hkt"], r["hkjc_event_id"]))
    targets.sort(key=lambda r: (r["kickoff_hkt"], r["hkjc_event_id"]))
    _write_csv(CURRENT_OUT, CURRENT_COLUMNS, current)
    _write_csv(TARGET_OUT, TARGET_COLUMNS, targets)

    print(
        f"HKJC_DIRECT matches={len(match_rows)} had_rows={len(had_rows)} "
        f"current={len(current)} targets={len(targets)} horizon_h={args.horizon_hours:g}"
    )
    if not current:
        raise SystemExit("HKJC normalization produced zero current rows")
    if not targets:
        raise SystemExit("HKJC normalization produced zero pre-event HAD targets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
