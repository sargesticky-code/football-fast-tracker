"""Capture and score pre-match OddsMath 1X2 movement for Fast Tracker.

This is a history-preserving feed. It never uses in-play rows and never changes
HKJC fixtures. OddsMath is treated as a secondary market signal; HKJC remains
the canonical match identity.

Sampling policy:
- workflow runs every 30 minutes
- >4h before kickoff: keep one snapshot per hour
- <=4h before kickoff: keep every 30-minute snapshot
- history retained for 180 days

Movement is measured on de-vigged implied probability, not raw odds.
"""
from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

HKT = ZoneInfo("Asia/Hong_Kong")
UTC = timezone.utc
ROOT = Path(__file__).resolve().parent.parent

HKJC = ROOT / "data" / "hkjc_current.csv"
ALIASES = ROOT / "data" / "team_alias_registry.csv"
FOREBET = ROOT / "data" / "forebet_current.csv"
HISTORY = ROOT / "data" / "oddsmath_history.csv"
CURRENT = ROOT / "data" / "oddsmath_current.csv"
MOVEMENT = ROOT / "data" / "odds_movement.csv"

BASE = "https://www.oddsmath.com/football/matches/{date}/"
UA = "Mozilla/5.0 (compatible; FastTrackerOddsMovement/1.0)"

HISTORY_COLUMNS = [
    "captured_at_hkt", "snapshot_slot_hkt", "hkjc_event_id", "kickoff_hkt",
    "home_hkjc", "away_hkjc", "home_oddsmath", "away_oddsmath",
    "oddsmath_league", "bn", "odds_home", "odds_draw", "odds_away",
    "fair_home", "fair_draw", "fair_away", "match_confidence",
]
CURRENT_COLUMNS = HISTORY_COLUMNS
MOVEMENT_COLUMNS = [
    "captured_at_hkt", "kickoff_hkt", "hkjc_event_id", "home", "away",
    "movement_side", "now_odds", "odds_24h", "move_24h_pp",
    "odds_2h", "move_2h_pp", "vol_24h_pp", "signal",
    "model_side", "model_prob", "model_alignment", "match_confidence",
    "alert_score",
]

TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
DROP_TOKENS = {
    "fc", "cf", "sc", "afc", "ac", "fk", "ks", "sv", "if", "club",
    "football", "u23", "under23", "am",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in columns})
    tmp.replace(path)


def parse_dt(value: str) -> datetime | None:
    value = str(value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HKT)
    return dt.astimezone(HKT)


def to_float(value) -> float | None:
    try:
        x = float(str(value).strip().replace("%", ""))
        return x if math.isfinite(x) and x > 0 else None
    except (TypeError, ValueError):
        return None


def norm(value: str) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    parts = [p for p in s.split() if p not in DROP_TOKENS]
    return " ".join(parts)


def name_score(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.94
    return SequenceMatcher(None, na, nb, autojunk=False).ratio()


def load_aliases() -> dict[str, str]:
    out: dict[str, str] = {}
    for r in read_csv(ALIASES):
        alias = norm(r.get("forebet_alias", ""))
        canonical = str(r.get("canonical_hkjc_name") or "").strip()
        if alias and canonical:
            out[alias] = canonical
            out.setdefault(norm(canonical), canonical)
    return out


def canonical_source_name(name: str, aliases: dict[str, str]) -> str:
    return aliases.get(norm(name), name)


def fair_probs(h: float, d: float, a: float) -> tuple[float, float, float]:
    ih, id_, ia = 1 / h, 1 / d, 1 / a
    total = ih + id_ + ia
    return ih / total, id_ / total, ia / total


def fetch_day(session: requests.Session, day) -> list[dict]:
    url = BASE.format(date=day.isoformat())
    res = session.get(url, headers={"User-Agent": UA}, timeout=30)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "lxml")
    rows: list[dict] = []
    league = ""

    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        first = cells[0].strip()
        if not TIME_RE.match(first):
            text = " ".join(cells).strip()
            if text and "BN" not in text and "Margin" not in text:
                league = text[:160]
            continue
        if len(cells) < 9:
            continue

        # OddsMath fixtures use: time, home, separator, away, status, BN, 1, X, 2, margin.
        home = cells[1] if len(cells) > 1 else ""
        away = cells[3] if len(cells) > 3 else ""
        status = cells[4] if len(cells) > 4 else ""
        if re.search(r"in-?play|finished", status, re.I):
            continue

        h = to_float(cells[-4])
        d = to_float(cells[-3])
        a = to_float(cells[-2])
        if not home or not away or not all((h, d, a)):
            continue

        hour, minute = map(int, first.split(":"))
        kickoff_utc = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)
        bn = cells[-5] if len(cells) >= 5 else ""
        fh, fd, fa = fair_probs(h, d, a)
        rows.append({
            "kickoff_utc": kickoff_utc,
            "home": home.strip(),
            "away": away.strip(),
            "league": league,
            "bn": bn,
            "odds_home": h,
            "odds_draw": d,
            "odds_away": a,
            "fair_home": fh,
            "fair_draw": fd,
            "fair_away": fa,
        })
    return rows


def current_hkjc(now: datetime) -> list[dict]:
    out = []
    for r in read_csv(HKJC):
        ko = parse_dt(r.get("kickoff_hkt", ""))
        status = str(r.get("status") or "").upper()
        if not ko or ko <= now or status != "PREEVENT":
            continue
        event_id = str(r.get("hkjc_event_id") or "").strip()
        if not event_id:
            continue
        out.append({
            "event_id": event_id,
            "kickoff": ko,
            "home": str(r.get("home_en") or r.get("home_zh") or "").strip(),
            "away": str(r.get("away_en") or r.get("away_zh") or "").strip(),
        })
    return out


def match_events(source: list[dict], targets: list[dict], aliases: dict[str, str]) -> list[dict]:
    matched = []
    for src in source:
        src_home = canonical_source_name(src["home"], aliases)
        src_away = canonical_source_name(src["away"], aliases)
        candidates = []
        for t in targets:
            diff = abs((t["kickoff"].astimezone(UTC) - src["kickoff_utc"]).total_seconds()) / 60
            if diff > 90:
                continue
            hs = name_score(src_home, t["home"])
            aw = name_score(src_away, t["away"])
            score = (hs + aw) / 2
            if hs >= 0.66 and aw >= 0.66 and score >= 0.78:
                candidates.append((score, -diff, hs, aw, t))
        if not candidates:
            continue
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        best = candidates[0]
        second = candidates[1][0] if len(candidates) > 1 else 0.0
        if best[0] < 0.90 and second and best[0] - second < 0.04:
            continue
        rec = dict(src)
        rec["target"] = best[4]
        rec["confidence"] = best[0]
        matched.append(rec)
    return matched


def slot_for(now: datetime) -> datetime:
    minute = 0 if now.minute < 30 else 30
    return now.replace(minute=minute, second=0, microsecond=0)


def history_row(m: dict, captured: datetime, slot: datetime) -> dict:
    t = m["target"]
    return {
        "captured_at_hkt": captured.isoformat(),
        "snapshot_slot_hkt": slot.isoformat(),
        "hkjc_event_id": t["event_id"],
        "kickoff_hkt": t["kickoff"].strftime("%Y-%m-%d %H:%M"),
        "home_hkjc": t["home"],
        "away_hkjc": t["away"],
        "home_oddsmath": m["home"],
        "away_oddsmath": m["away"],
        "oddsmath_league": m["league"],
        "bn": m["bn"],
        "odds_home": f'{m["odds_home"]:.4f}',
        "odds_draw": f'{m["odds_draw"]:.4f}',
        "odds_away": f'{m["odds_away"]:.4f}',
        "fair_home": f'{m["fair_home"]:.6f}',
        "fair_draw": f'{m["fair_draw"]:.6f}',
        "fair_away": f'{m["fair_away"]:.6f}',
        "match_confidence": f'{m["confidence"]:.3f}',
    }


def nearest(rows: list[dict], target: datetime, tolerance: timedelta) -> dict | None:
    candidates = []
    for r in rows:
        dt = parse_dt(r.get("captured_at_hkt", ""))
        if not dt:
            continue
        delta = abs(dt - target)
        if delta <= tolerance:
            candidates.append((delta, r))
    return min(candidates, key=lambda x: x[0])[1] if candidates else None


def f(row: dict | None, key: str) -> float | None:
    if not row:
        return None
    try:
        return float(row.get(key, ""))
    except (TypeError, ValueError):
        return None


def model_map() -> dict[str, tuple[str, float]]:
    out = {}
    for r in read_csv(FOREBET):
        event_id = str(r.get("hkjc_event_id") or "").strip()
        if not event_id:
            continue
        probs = {
            "H": to_float(r.get("prob_home")) or 0.0,
            "D": to_float(r.get("prob_draw")) or 0.0,
            "A": to_float(r.get("prob_away")) or 0.0,
        }
        side = max(probs, key=probs.get)
        out[event_id] = (side, probs[side])
    return out


def movement_rows(history: list[dict], targets: list[dict], now: datetime) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in history:
        groups[str(r.get("hkjc_event_id") or "")].append(r)
    models = model_map()
    out = []

    side_keys = {
        "H": ("fair_home", "odds_home"),
        "D": ("fair_draw", "odds_draw"),
        "A": ("fair_away", "odds_away"),
    }

    for t in targets:
        event_id = t["event_id"]
        rows = groups.get(event_id, [])
        rows.sort(key=lambda r: parse_dt(r.get("captured_at_hkt", "")) or datetime.min.replace(tzinfo=HKT))
        if not rows:
            continue
        latest = rows[-1]
        last24 = [r for r in rows if (parse_dt(r.get("captured_at_hkt", "")) or now) >= now - timedelta(hours=24)]
        b24 = nearest(rows, now - timedelta(hours=24), timedelta(hours=3))
        b2 = nearest(rows, now - timedelta(hours=2), timedelta(minutes=75))

        metrics = {}
        for side, (pk, ok) in side_keys.items():
            current = f(latest, pk)
            p24 = f(b24, pk)
            p2 = f(b2, pk)
            d24 = current - p24 if current is not None and p24 is not None else None
            d2 = current - p2 if current is not None and p2 is not None else None
            vals = [f(r, pk) for r in last24]
            vals = [x for x in vals if x is not None]
            vol = max(vals) - min(vals) if len(vals) >= 2 else None
            strength = max(abs(d24) if d24 is not None else 0.0,
                           abs(d2) if d2 is not None else 0.0,
                           vol if vol is not None else 0.0)
            metrics[side] = (strength, d24, d2, vol, current, pk, ok)

        side = max(metrics, key=lambda s: metrics[s][0])
        _, d24, d2, vol, _, pk, ok = metrics[side]
        now_odds = f(latest, ok)
        odds24 = f(b24, ok)
        odds2 = f(b2, ok)

        signal = "STABLE"
        if b24 is None or b2 is None:
            signal = "COLLECTING"
        else:
            if d24 is not None and d2 is not None and d24 * d2 < 0 and abs(d24) >= 0.03 and abs(d2) >= 0.03:
                signal = "REVERSAL"
            elif d2 is not None and d2 >= 0.03:
                signal = "LATE STEAM"
            elif d2 is not None and d2 <= -0.03:
                signal = "LATE DRIFT"
            elif d24 is not None and d24 >= 0.05:
                signal = "24H STEAM"
            elif d24 is not None and d24 <= -0.05:
                signal = "24H DRIFT"
            elif vol is not None and vol >= 0.08:
                signal = "HIGH VOLATILITY"

        score = max(
            abs(d24) / 0.05 if d24 is not None else 0.0,
            abs(d2) / 0.03 if d2 is not None else 0.0,
            vol / 0.08 if vol is not None else 0.0,
        )
        alert_score = score if signal not in {"STABLE", "COLLECTING"} else 0.0

        model_side, model_prob = models.get(event_id, ("", 0.0))
        if not model_side:
            align = "NO MODEL"
        elif ((d2 if d2 is not None else d24) or 0) > 0:
            align = "YES" if model_side == side else "NO"
        elif model_side == side:
            align = "CONFLICT"
        else:
            align = "NEUTRAL"

        out.append({
            "captured_at_hkt": latest.get("captured_at_hkt", ""),
            "kickoff_hkt": t["kickoff"].isoformat(timespec="minutes"),
            "hkjc_event_id": event_id,
            "home": t["home"],
            "away": t["away"],
            "movement_side": side,
            "now_odds": f"{now_odds:.3f}" if now_odds else "",
            "odds_24h": f"{odds24:.3f}" if odds24 else "",
            "move_24h_pp": f"{d24 * 100:.2f}" if d24 is not None else "",
            "odds_2h": f"{odds2:.3f}" if odds2 else "",
            "move_2h_pp": f"{d2 * 100:.2f}" if d2 is not None else "",
            "vol_24h_pp": f"{vol * 100:.2f}" if vol is not None else "",
            "signal": signal,
            "model_side": model_side,
            "model_prob": f"{model_prob:.1f}" if model_side else "",
            "model_alignment": align,
            "match_confidence": latest.get("match_confidence", ""),
            "alert_score": f"{alert_score:.3f}",
        })

    out.sort(key=lambda r: (-float(r["alert_score"] or 0), r["kickoff_hkt"], r["hkjc_event_id"]))
    return out


def main() -> int:
    now = datetime.now(HKT).replace(microsecond=0)
    targets = current_hkjc(now)
    aliases = load_aliases()

    session = requests.Session()
    utc_day = now.astimezone(UTC).date()
    source = []
    for offset in (-1, 0, 1, 2):
        day = utc_day + timedelta(days=offset)
        try:
            source.extend(fetch_day(session, day))
        except Exception as exc:
            print(f"WARN ODDSMATH day={day} error={type(exc).__name__}:{exc}")

    matched = match_events(source, targets, aliases)
    slot = slot_for(now)

    existing = read_csv(HISTORY)
    existing_keys = {
        (str(r.get("snapshot_slot_hkt") or ""), str(r.get("hkjc_event_id") or ""))
        for r in existing
    }
    new_rows = []
    for m in matched:
        hours_to_ko = (m["target"]["kickoff"] - now).total_seconds() / 3600
        # Hourly outside the last 4 hours; half-hourly inside it.
        if hours_to_ko > 4 and slot.minute == 30:
            continue
        row = history_row(m, now, slot)
        key = (row["snapshot_slot_hkt"], row["hkjc_event_id"])
        if key not in existing_keys:
            new_rows.append(row)
            existing_keys.add(key)

    cutoff = now - timedelta(days=180)
    history = []
    for r in existing + new_rows:
        dt = parse_dt(r.get("captured_at_hkt", ""))
        if dt and dt >= cutoff:
            history.append(r)
    history.sort(key=lambda r: (r.get("captured_at_hkt", ""), r.get("hkjc_event_id", "")))
    write_csv(HISTORY, HISTORY_COLUMNS, history)

    current = [history_row(m, now, slot) for m in matched]
    current.sort(key=lambda r: (r["kickoff_hkt"], r["hkjc_event_id"]))
    write_csv(CURRENT, CURRENT_COLUMNS, current)

    movement = movement_rows(history, targets, now)
    write_csv(MOVEMENT, MOVEMENT_COLUMNS, movement)

    alerts = sum(float(r.get("alert_score") or 0) >= 1 for r in movement)
    print(
        f"ODDSMATH source={len(source)} hkjc_pre={len(targets)} matched={len(matched)} "
        f"new_snapshots={len(new_rows)} history={len(history)} movement={len(movement)} alerts={alerts}"
    )
    if not source:
        raise SystemExit("OddsMath returned zero fixture rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
