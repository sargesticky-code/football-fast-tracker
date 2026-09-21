"""Phase 2 Layer 1: read-only HKJC universe freshness gate.

This module NEVER writes to the production Google Sheet and NEVER consumes
Phase 1 probabilities or Phase 3 live signals. It accepts an HKJC CSV snapshot,
validates freshness/status/kickoff, and emits only the fixture identity universe
that Phase 2 is allowed to map to external team IDs.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

HKT = timezone(timedelta(hours=8))
ENDED = {"MATCHENDED", "INPLAYMATCHENDED"}

@dataclass(frozen=True)
class Phase2Fixture:
    fetched_at_hkt: datetime
    match_id: str
    hkjc_event_id: str
    kickoff_hkt: datetime
    tournament: str
    home_en: str
    away_en: str


def _dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"timezone required: {value}")
    return dt.astimezone(HKT)


def load_current_universe(path: str | Path, *, now: datetime | None = None,
                          max_snapshot_age: timedelta = timedelta(hours=3),
                          horizon: timedelta = timedelta(hours=48)) -> list[Phase2Fixture]:
    now = (now or datetime.now(HKT)).astimezone(HKT)
    rows = list(csv.DictReader(Path(path).open(encoding="utf-8-sig", newline="")))
    if not rows:
        raise RuntimeError("HKJC snapshot empty; fail closed")

    fetched_values = {_dt(r["fetched_at_hkt"]) for r in rows if r.get("fetched_at_hkt")}
    if len(fetched_values) != 1:
        raise RuntimeError("HKJC snapshot has mixed/missing fetch timestamps; fail closed")
    fetched_at = next(iter(fetched_values))
    age = now - fetched_at
    if age < timedelta(minutes=-5) or age > max_snapshot_age:
        raise RuntimeError(f"HKJC snapshot stale/invalid age={age}; fail closed")

    out: list[Phase2Fixture] = []
    seen: set[str] = set()
    for r in rows:
        event_id = (r.get("hkjc_event_id") or "").strip()
        status = (r.get("status") or "").strip().upper()
        if not event_id.startswith("FB") or status in ENDED:
            continue
        kickoff = _dt(r["kickoff_hkt"])
        if not (now <= kickoff <= now + horizon):
            continue
        home = (r.get("home_en") or "").strip()
        away = (r.get("away_en") or "").strip()
        if not home or not away or event_id in seen:
            continue
        seen.add(event_id)
        out.append(Phase2Fixture(fetched_at, (r.get("match_id") or "").strip(),
                                 event_id, kickoff, (r.get("tournament") or "").strip(),
                                 home, away))
    return sorted(out, key=lambda x: (x.kickoff_hkt, x.hkjc_event_id))


def write_identity_universe(fixtures: Iterable[Phase2Fixture], path: str | Path) -> None:
    """Write an isolated Phase-2-only identity input; never a production feed."""
    fields = ["fetched_at_hkt", "match_id", "hkjc_event_id", "kickoff_hkt", "tournament", "home_en", "away_en"]
    with Path(path).open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for f in fixtures:
            w.writerow({
                "fetched_at_hkt": f.fetched_at_hkt.isoformat(), "match_id": f.match_id,
                "hkjc_event_id": f.hkjc_event_id, "kickoff_hkt": f.kickoff_hkt.isoformat(),
                "tournament": f.tournament, "home_en": f.home_en, "away_en": f.away_en,
            })
