from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scrape_forebet import team_score

ROOT = Path(__file__).resolve().parent.parent
CURRENT = ROOT / "data" / "forebet_current.csv"
REGISTRY = ROOT / "data" / "team_alias_registry.csv"
HKT = ZoneInfo("Asia/Hong_Kong")

FIELDS = [
    "forebet_alias",
    "canonical_hkjc_name",
    "confidence",
    "first_seen_hkt",
    "last_seen_hkt",
    "match_count",
    "status",
    "source",
]


def clean(v: object) -> str:
    return str(v or "").strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def key(alias: str) -> str:
    return " ".join(clean(alias).casefold().split())


def main() -> int:
    now = datetime.now(HKT).isoformat(timespec="seconds")
    store: dict[str, dict[str, str]] = {}

    for row in read_csv(REGISTRY):
        alias = clean(row.get("forebet_alias"))
        canonical = clean(row.get("canonical_hkjc_name"))
        if not alias or not canonical:
            continue
        store[key(alias)] = {f: clean(row.get(f)) for f in FIELDS}

    learned = 0
    conflicts = 0
    for row in read_csv(CURRENT):
        pairs = (
            (clean(row.get("home_team")), clean(row.get("hkjc_home_team"))),
            (clean(row.get("away_team")), clean(row.get("hkjc_away_team"))),
        )
        for alias, canonical in pairs:
            if not alias or not canonical:
                continue
            confidence = team_score(alias, canonical)
            # Only auto-learn highly reliable team mappings. Lower-confidence
            # rows stay available for matching but are not persisted as aliases.
            if confidence < 0.90:
                continue

            k = key(alias)
            old = store.get(k)
            if old and clean(old.get("canonical_hkjc_name")) != canonical:
                old["status"] = "CONFLICT"
                old["last_seen_hkt"] = now
                conflicts += 1
                continue

            if old is None:
                store[k] = {
                    "forebet_alias": alias,
                    "canonical_hkjc_name": canonical,
                    "confidence": f"{confidence:.3f}",
                    "first_seen_hkt": now,
                    "last_seen_hkt": now,
                    "match_count": "1",
                    "status": "ACTIVE",
                    "source": "AUTO_HIGH_CONFIDENCE",
                }
                learned += 1
            else:
                old["last_seen_hkt"] = now
                old["confidence"] = f"{max(float(old.get('confidence') or 0), confidence):.3f}"
                old["match_count"] = str(int(float(old.get("match_count") or 0)) + 1)
                if old.get("status") != "MANUAL":
                    old["status"] = "ACTIVE"
                if not old.get("source"):
                    old["source"] = "AUTO_HIGH_CONFIDENCE"

    rows = sorted(
        store.values(),
        key=lambda r: (clean(r.get("canonical_hkjc_name")).casefold(), clean(r.get("forebet_alias")).casefold()),
    )
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"TEAM_ALIAS_REGISTRY rows={len(rows)} learned={learned} conflicts={conflicts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
