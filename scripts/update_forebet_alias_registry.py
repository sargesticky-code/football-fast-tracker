from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from forebet_match_policy import team_score

ROOT = Path(__file__).resolve().parent.parent
CURRENT = ROOT / "data" / "forebet_current.csv"
AVAILABILITY = ROOT / "data" / "forebet_availability.csv"
REGISTRY = ROOT / "data" / "team_alias_registry.csv"
MANUAL = ROOT / "data" / "team_alias_manual.csv"
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

_SOURCE_NOISE = re.compile(
    r"(^\s*Title:\s*|Prediction,\s*Stats,\s*H2H|^\s*URL Source:|^\s*Markdown Content:)",
    re.I,
)


def clean(v: object) -> str:
    return str(v or "").strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def key(alias: str) -> str:
    return " ".join(clean(alias).casefold().split())


def source_noise(alias: str) -> bool:
    value = clean(alias)
    return bool(_SOURCE_NOISE.search(value) or len(value) > 80)


def main() -> int:
    now = datetime.now(HKT).isoformat(timespec="seconds")
    store: dict[str, dict[str, str]] = {}
    pruned_noise = 0

    for row in read_csv(REGISTRY):
        alias = clean(row.get("forebet_alias"))
        canonical = clean(row.get("canonical_hkjc_name"))
        status = clean(row.get("status")).upper()
        if not alias or not canonical:
            continue
        # MANUAL rows are explicit operator decisions. Auto-learned page-title
        # wrappers and similar metadata are invalid aliases and are discarded
        # on every rewrite so one bad parse cannot permanently poison matching.
        if status != "MANUAL" and source_noise(alias):
            pruned_noise += 1
            continue
        store[key(alias)] = {f: clean(row.get(f)) for f in FIELDS}

    # Manual aliases are operator-verified and authoritative.  Merge them
    # before auto-learning so future production runs can consume the same
    # canonical decisions directly from the registry as well.
    manual_rows = 0
    for row in read_csv(MANUAL):
        alias = clean(row.get("forebet_alias"))
        canonical = clean(row.get("canonical_hkjc_name"))
        if not alias or not canonical:
            continue
        k = key(alias)
        old = store.get(k, {})
        store[k] = {
            "forebet_alias": alias,
            "canonical_hkjc_name": canonical,
            "confidence": "1.000",
            "first_seen_hkt": clean(old.get("first_seen_hkt")) or now,
            "last_seen_hkt": now,
            "match_count": clean(old.get("match_count")) or "1",
            "status": "MANUAL",
            "source": "MANUAL_OVERRIDE",
        }
        manual_rows += 1

    learned = 0
    fixture_learned = 0
    conflicts = 0
    rejected_noise = 0

    # A Forebet fixture is identity evidence even when the provider publishes no
    # usable prediction model.  The availability layer now retains the actual
    # provider home/away names and promotes only strict, unique >=0.94 matches.
    # Persist those aliases here too so GitHub has the same learn-once dictionary
    # as Supabase rather than waiting for a future model row.
    for row in read_csv(AVAILABILITY):
        if clean(row.get("identity_status")).upper() != "VERIFIED":
            continue
        try:
            confidence = float(clean(row.get("fixture_match_score")) or 0)
        except ValueError:
            confidence = 0.0
        if confidence < 0.94:
            continue
        pairs = (
            (clean(row.get("source_home_team")), clean(row.get("home_en"))),
            (clean(row.get("source_away_team")), clean(row.get("away_en"))),
        )
        for alias, canonical in pairs:
            if not alias or not canonical or source_noise(alias):
                continue
            k = key(alias)
            old = store.get(k)
            if old and clean(old.get("canonical_hkjc_name")) != canonical:
                if clean(old.get("status")).upper() == "MANUAL":
                    conflicts += 1
                    continue
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
                    "source": "FOREBET_LIVESCORE_IDENTITY",
                }
                learned += 1
                fixture_learned += 1
            else:
                old["last_seen_hkt"] = now
                old["confidence"] = f"{max(float(old.get('confidence') or 0), confidence):.3f}"
                old["match_count"] = str(int(float(old.get("match_count") or 0)) + 1)
                if old.get("status") != "MANUAL":
                    old["status"] = "ACTIVE"
                    old["source"] = old.get("source") or "FOREBET_LIVESCORE_IDENTITY"

    for row in read_csv(CURRENT):
        pairs = (
            (clean(row.get("home_team")), clean(row.get("hkjc_home_team"))),
            (clean(row.get("away_team")), clean(row.get("hkjc_away_team"))),
        )
        for alias, canonical in pairs:
            if not alias or not canonical:
                continue
            if source_noise(alias):
                rejected_noise += 1
                continue
            confidence = team_score(alias, canonical)
            # The production match policy removes stable source noise and
            # handles distinctive club acronyms before this threshold. Safely
            # matched names can therefore persist across future fixtures.
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
                    "source": "AUTO_MATCH_POLICY",
                }
                learned += 1
            else:
                old["last_seen_hkt"] = now
                old["confidence"] = f"{max(float(old.get('confidence') or 0), confidence):.3f}"
                old["match_count"] = str(int(float(old.get("match_count") or 0)) + 1)
                if old.get("status") != "MANUAL":
                    old["status"] = "ACTIVE"
                if not old.get("source"):
                    old["source"] = "AUTO_MATCH_POLICY"

    rows = sorted(
        store.values(),
        key=lambda r: (clean(r.get("canonical_hkjc_name")).casefold(), clean(r.get("forebet_alias")).casefold()),
    )
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"TEAM_ALIAS_REGISTRY rows={len(rows)} manual={manual_rows} learned={learned} "
        f"fixture_learned={fixture_learned} conflicts={conflicts} "
        f"pruned_noise={pruned_noise} rejected_noise={rejected_noise}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
