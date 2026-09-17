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
    by_id = {
        str(row.get("hkjc_event_id") or "").strip(): row
        for row in availability
        if str(row.get("hkjc_event_id") or "").strip()
    }

    missing = sorted(feed_ids - set(by_id))
    if missing:
        raise SystemExit(
            "Forebet model rows missing availability records: " + ",".join(missing)
        )

    now = datetime.now(HKT).isoformat(timespec="seconds")
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
    if stale_models:
        raise SystemExit(
            "Availability MODEL state without current model row: "
            + ",".join(stale_models)
        )

    fieldnames = list(availability[0].keys())
    tmp = AVAILABILITY.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(availability)
    tmp.replace(AVAILABILITY)

    print(
        f"FOREBET_AVAILABILITY_RECONCILE feed={len(feed_ids)} "
        f"models={len(model_ids)} promoted={len(promoted)} "
        f"promoted_ids={','.join(promoted) if promoted else '-'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
