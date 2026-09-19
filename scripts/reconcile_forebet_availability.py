"""Reconcile Forebet availability after active-model carry-forward.

The 1X2 fetch writes availability while it is still constructing the current
model feed.  A later carry-forward step may legitimately restore an existing
model for an HKJC event when the live Forebet refresh is partial.  This gate
runs after all model restoration and makes the availability file agree with
the actual production model feed.

Invariant after this script:
- every event in forebet_current.csv is state=MODEL in forebet_availability.csv;
- every availability state=MODEL has a corresponding current model row.

No prediction is invented here.  The script only promotes an event to MODEL
when a usable row already exists in forebet_current.csv.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CURRENT = ROOT / "data" / "forebet_current.csv"
AVAILABILITY = ROOT / "data" / "forebet_availability.csv"
HKT = ZoneInfo("Asia/Hong_Kong")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"missing production file: {path}")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    feed = read_csv(CURRENT)
    availability = read_csv(AVAILABILITY)
    if not feed or not availability:
        raise SystemExit("zero Forebet model or availability rows")

    feed_ids = {
        str(row.get("hkjc_event_id") or "").strip()
        for row in feed
        if str(row.get("hkjc_event_id") or "").strip()
    }
    feed_by_id = {
        str(row.get("hkjc_event_id") or "").strip(): row
        for row in feed
        if str(row.get("hkjc_event_id") or "").strip()
    }
    by_id = {
        str(row.get("hkjc_event_id") or "").strip(): row
        for row in availability
        if str(row.get("hkjc_event_id") or "").strip()
    }

    now = datetime.now(HKT).isoformat(timespec="seconds")
    missing = sorted(feed_ids - set(by_id))
    inserted: list[str] = []
    for event_id in missing:
        model = feed_by_id[event_id]
        kickoff = str(model.get("hkjc_kickoff_hkt") or "").strip()
        match_date = str(model.get("match_date") or "").strip()
        if not match_date and kickoff:
            match_date = kickoff[:10]
        row = {
            "checked_at_hkt": now,
            "match_date": match_date,
            "kickoff_hkt": kickoff,
            "hkjc_event_id": event_id,
            "league_zh": str(model.get("hkjc_league") or "").strip(),
            "home_en": str(model.get("hkjc_home_team") or model.get("home_team") or "").strip(),
            "away_en": str(model.get("hkjc_away_team") or model.get("away_team") or "").strip(),
            "state": "MODEL",
            "reason": "usable_forebet_prediction_model_inserted_by_reconcile",
        }
        availability.append(row)
        by_id[event_id] = row
        inserted.append(event_id)

    promoted: list[str] = []
    for event_id in sorted(feed_ids):
        row = by_id[event_id]
        if str(row.get("state") or "").strip().upper() != "MODEL":
            row["state"] = "MODEL"
            row["reason"] = "usable_forebet_prediction_model_after_reconcile"
            row["checked_at_hkt"] = now
            promoted.append(event_id)

    model_ids = {
        event_id
        for event_id, row in by_id.items()
        if str(row.get("state") or "").strip().upper() == "MODEL"
    }
    stale_models = sorted(model_ids - feed_ids)
    demoted: list[str] = []
    for event_id in stale_models:
        row = by_id[event_id]
        row["state"] = "UNRESOLVED"
        row["reason"] = "current_model_missing_after_reconcile"
        row["checked_at_hkt"] = now
        demoted.append(event_id)

    model_ids = {
        event_id
        for event_id, row in by_id.items()
        if str(row.get("state") or "").strip().upper() == "MODEL"
    }

    fieldnames = list(availability[0].keys())
    tmp = AVAILABILITY.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(availability)
    tmp.replace(AVAILABILITY)

    print(
        f"FOREBET_AVAILABILITY_RECONCILE feed={len(feed_ids)} "
        f"models={len(model_ids)} inserted={len(inserted)} promoted={len(promoted)} "
        f"demoted={len(demoted)} "
        f"inserted_ids={','.join(inserted) if inserted else '-'} "
        f"promoted_ids={','.join(promoted) if promoted else '-'} "
        f"demoted_ids={','.join(demoted) if demoted else '-'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
