"""Maintain a durable team identity and source-alias registry.

HKJC numeric team ids are the canonical anchor because they are stable inside
HKJC's GraphQL data and are captured before any cross-source name matching.
Forebet/HKJC English/HKJC Chinese spellings are stored as aliases with evidence
from an exact FBxxxx event mapping. The registry is append/update only and can
grow for years without wildcard matching becoming authoritative.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")
ROOT = Path(__file__).resolve().parent.parent
TEAM_MAP = ROOT / "data" / "hkjc_current_teams.csv"
FOREBET = ROOT / "data" / "forebet_current.csv"
IDENTITY = ROOT / "data" / "team_identity.csv"
ALIASES = ROOT / "data" / "team_aliases.csv"
UNRESOLVED = ROOT / "data" / "team_alias_unresolved.csv"

IDENTITY_COLUMNS = [
    "canonical_team_id", "hkjc_team_id", "canonical_name_en",
    "first_seen_hkt", "last_seen_hkt", "last_event_id",
]
ALIAS_COLUMNS = [
    "canonical_team_id", "source", "alias", "normalized_alias", "confidence",
    "status", "first_seen_hkt", "last_seen_hkt", "evidence_event_id",
]
UNRESOLVED_COLUMNS = [
    "fetched_at_hkt", "hkjc_event_id", "side", "hkjc_team_id", "hkjc_name_en",
    "source", "source_alias", "match_score", "reason",
]


def norm(value: str) -> str:
    value = "".join(c for c in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(c))
    value = value.casefold().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in columns})
    tmp.replace(path)


def confidence(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v > 1.0:
        v /= 100.0
    return max(0.0, min(1.0, v))


def main() -> int:
    teams = read(TEAM_MAP)
    feed = {r.get("hkjc_event_id", ""): r for r in read(FOREBET) if r.get("hkjc_event_id")}
    now = datetime.now(HKT).replace(microsecond=0).isoformat()

    identities = {r.get("canonical_team_id", ""): r for r in read(IDENTITY) if r.get("canonical_team_id")}
    aliases = {
        (r.get("canonical_team_id", ""), r.get("source", ""), r.get("normalized_alias", "")): r
        for r in read(ALIASES)
        if r.get("canonical_team_id") and r.get("source") and r.get("normalized_alias")
    }
    unresolved = []

    def touch_identity(team_id: str, name: str, event_id: str):
        cid = f"hkjc:{team_id}"
        old = identities.get(cid)
        if old is None:
            old = {
                "canonical_team_id": cid,
                "hkjc_team_id": team_id,
                "canonical_name_en": name,
                "first_seen_hkt": now,
            }
            identities[cid] = old
        if name and not old.get("canonical_name_en"):
            old["canonical_name_en"] = name
        old["last_seen_hkt"] = now
        old["last_event_id"] = event_id
        return cid

    def touch_alias(cid: str, source: str, alias: str, conf: float, event_id: str, status: str = "CONFIRMED_EVENT"):
        alias = (alias or "").strip()
        normalized = norm(alias)
        if not normalized:
            return
        key = (cid, source, normalized)
        old = aliases.get(key)
        if old is None:
            old = {
                "canonical_team_id": cid,
                "source": source,
                "alias": alias,
                "normalized_alias": normalized,
                "confidence": f"{conf:.3f}",
                "status": status,
                "first_seen_hkt": now,
            }
            aliases[key] = old
        else:
            old_conf = confidence(old.get("confidence"))
            if conf > old_conf:
                old["confidence"] = f"{conf:.3f}"
                old["alias"] = alias
            if status == "CONFIRMED_EVENT":
                old["status"] = status
        old["last_seen_hkt"] = now
        old["evidence_event_id"] = event_id

    for t in teams:
        event_id = t.get("hkjc_event_id", "")
        f = feed.get(event_id, {})
        score = confidence(f.get("match_score", ""))
        for side in ("home", "away"):
            team_id = str(t.get(f"{side}_id") or "").strip()
            name = str(t.get(side) or "").strip()
            if not team_id or not name:
                continue
            cid = touch_identity(team_id, name, event_id)
            touch_alias(cid, "HKJC_EN", name, 1.0, event_id)

            zh = str(f.get(f"hkjc_{side}_zh") or "").strip()
            if zh:
                # Chinese aliases are preserved verbatim; normalized_alias is
                # English-centric only for candidate matching, so use itself.
                key = (cid, "HKJC_ZH", zh)
                old = aliases.get(key)
                if old is None:
                    old = {
                        "canonical_team_id": cid, "source": "HKJC_ZH", "alias": zh,
                        "normalized_alias": zh, "confidence": "1.000",
                        "status": "CONFIRMED_EVENT", "first_seen_hkt": now,
                    }
                    aliases[key] = old
                old["last_seen_hkt"] = now
                old["evidence_event_id"] = event_id

            fb_alias = str(f.get(f"{side}_team") or "").strip()
            if fb_alias:
                if score >= 0.90:
                    touch_alias(cid, "FOREBET", fb_alias, score, event_id)
                else:
                    unresolved.append({
                        "fetched_at_hkt": now,
                        "hkjc_event_id": event_id,
                        "side": side.upper(),
                        "hkjc_team_id": team_id,
                        "hkjc_name_en": name,
                        "source": "FOREBET",
                        "source_alias": fb_alias,
                        "match_score": f"{score:.3f}",
                        "reason": "EVENT_MATCH_SCORE_BELOW_0.90",
                    })

    identity_rows = sorted(identities.values(), key=lambda r: r.get("canonical_team_id", ""))
    alias_rows = sorted(aliases.values(), key=lambda r: (r.get("canonical_team_id", ""), r.get("source", ""), r.get("normalized_alias", "")))
    write(IDENTITY, IDENTITY_COLUMNS, identity_rows)
    write(ALIASES, ALIAS_COLUMNS, alias_rows)
    write(UNRESOLVED, UNRESOLVED_COLUMNS, unresolved)
    print(
        f"TEAM_REGISTRY identities={len(identity_rows)} aliases={len(alias_rows)} "
        f"current_events={len(teams)} unresolved={len(unresolved)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
