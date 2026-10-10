"""Validate existing Forebet match feed for the isolated canonical publisher.

No scraping, matching or capture occurs here. Malformed/old rows fail closed.
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HKT = timezone(timedelta(hours=8))
ID_RE = re.compile(r"^[A-Za-z0-9:_-]{2,80}$")
SCORE_RE = re.compile(r"^[0-9]{1,2} *- *[0-9]{1,2}$")
REQUIRED = ("hkjc_event_id", "hkjc_home_team", "hkjc_away_team",
            "hkjc_kickoff_hkt", "home_team", "away_team", "fetched_at_hkt",
            "prob_home", "prob_draw", "prob_away", "prediction_1x2",
            "predicted_score", "avg_goals", "match_score")


def parse_hkt(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.strip())
    return (parsed.replace(tzinfo=HKT) if parsed.tzinfo is None else parsed).astimezone(timezone.utc)


def validated_rows(feed: list[dict], availability: list[dict],
                   now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    state = {r.get("hkjc_event_id"): r.get("state") for r in availability}
    out = []
    seen = set()
    for row in feed:
        missing = [k for k in REQUIRED if not str(row.get(k) or "").strip()]
        if missing:
            raise ValueError(f"model incomplete: {','.join(missing)}")
        match_id = row["hkjc_event_id"].strip()
        if not ID_RE.fullmatch(match_id) or match_id in seen:
            raise ValueError("invalid or duplicate fixture ID")
        seen.add(match_id)
        if state.get(match_id) != "MODEL":
            raise ValueError("model not approved by availability reconciliation")
        capture = parse_hkt(row["fetched_at_hkt"])
        kickoff = parse_hkt(row["hkjc_kickoff_hkt"])
        if not now - timedelta(hours=72) <= capture <= now + timedelta(minutes=10):
            raise ValueError("capture is stale or future-dated")
        if not now - timedelta(hours=12) <= kickoff <= now + timedelta(days=15):
            raise ValueError("fixture outside publication horizon")
        probs = [float(row[k]) for k in ("prob_home", "prob_draw", "prob_away")]
        if any(not 0 <= p <= 100 for p in probs) or not 98 <= sum(probs) <= 102:
            raise ValueError("invalid HDA probabilities")
        pick = row["prediction_1x2"].strip()
        if pick not in ("1", "X", "2") or not SCORE_RE.fullmatch(row["predicted_score"].strip()):
            raise ValueError("invalid prediction")
        confidence = float(row["match_score"])
        if not 0.94 <= confidence <= 1.0:
            raise ValueError("match confidence not verified")
        average_goals = float(row["avg_goals"])
        if not math.isfinite(average_goals) or not 0 < average_goals <= 12:
            raise ValueError("invalid Forebet average goals")
        out.append({
            "match_id": match_id, "captured_at": capture.isoformat(),
            "kickoff": kickoff.isoformat(), "canonical_home": row["hkjc_home_team"].strip(),
            "canonical_away": row["hkjc_away_team"].strip(),
            "source_home": row["home_team"].strip(), "source_away": row["away_team"].strip(),
            "home": probs[0], "draw": probs[1], "away": probs[2],
            "pick": pick, "score": row["predicted_score"].strip(),
            "avg_goals": average_goals, "match_score": confidence, "match_date": row.get("match_date", ""),
            "kickoff_text": row.get("kickoff_text", ""), "league": row.get("league_short", ""),
        })
    return out


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    feed = read_csv(Path("data/forebet_current.csv"))
    availability = read_csv(Path("data/forebet_availability.csv"))
    try:
        rows = validated_rows(feed, availability)
    except (ValueError, TypeError, OverflowError) as error:
        print(f"FOREBET_PUBLISH_REJECTED {error}", file=sys.stderr)
        return 2
    Path("/tmp/forebet-canonical-payload.json").write_text(json.dumps({"rows": rows}))
    print(f"FOREBET_PUBLISH_VALIDATED models={len(rows)}")
    if not rows:
        print("FOREBET_CAPTURE_UNAVAILABLE no current verified predictions; no publication request")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
