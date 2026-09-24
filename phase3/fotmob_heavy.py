"""Phase 3 Layer 6 FotMob heavy-detail adapter.

Normalizes recorded/live FotMob match-detail payloads into the HeavyLane contract.
It performs no identity matching and no HKJC eligibility decisions.
"""
from typing import Any


def _number(value: Any) -> Any:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip().replace("%", "")
        try:
            return float(text) if "." in text else int(text)
        except ValueError:
            return None
    return None


def _pair(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        home = _number(value.get("home", value.get("homeValue")))
        away = _number(value.get("away", value.get("awayValue")))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        home, away = _number(value[0]), _number(value[1])
    else:
        return None
    if home is None and away is None:
        return None
    return {"home": home, "away": away}


_ALIASES = {
    "xg": ("expected_goals", "expectedGoals", "xG", "xg"),
    "shots": ("total_shots", "totalShots", "shots"),
    "shots_on_target": ("shots_on_target", "shotsOnTarget"),
    "possession": ("possession", "ballPossession"),
    "box_touches": ("touches_in_opposition_box", "touchesInOppositionBox", "boxTouches"),
    "big_chances": ("big_chances", "bigChances"),
    "corners": ("corners", "cornerKicks"),
}


def _walk_stats(payload: dict[str, Any]):
    stats = payload.get("stats") or payload.get("content", {}).get("stats") or {}
    if isinstance(stats, dict):
        for key, value in stats.items():
            yield str(key), value
            if isinstance(value, dict):
                for inner_key, inner_value in value.items():
                    yield str(inner_key), inner_value
    elif isinstance(stats, list):
        for group in stats:
            if not isinstance(group, dict):
                continue
            for item in group.get("stats", group.get("items", [])) or []:
                if isinstance(item, dict):
                    yield str(item.get("key") or item.get("title") or item.get("name") or ""), item


def normalize_fotmob_heavy(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return only observed heavy fields; absent fields remain absent/None."""
    payload = payload or {}
    lookup: dict[str, Any] = {}
    for key, value in _walk_stats(payload):
        lookup[key.lower().replace(" ", "").replace("_", "")] = value

    out: dict[str, Any] = {}
    for field, aliases in _ALIASES.items():
        pair = None
        for alias in aliases:
            norm = alias.lower().replace(" ", "").replace("_", "")
            raw = lookup.get(norm)
            if isinstance(raw, dict) and "stats" in raw:
                raw = raw.get("stats")
            pair = _pair(raw)
            if pair is not None:
                break
        out[field] = pair

    content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    events = payload.get("events") or content.get("matchFacts", {}).get("events")
    momentum = payload.get("momentum") or content.get("momentum")
    out["events"] = events if isinstance(events, list) and events else None
    out["momentum"] = momentum if isinstance(momentum, (list, dict)) and momentum else None
    return out


def make_fotmob_detail_fetcher(fetch_json):
    """Adapt a single-match JSON fetch callable to HeavyLane.fetch_detail."""
    def fetch(target):
        if target.external_source.lower() != "fotmob":
            raise ValueError("unsupported heavy source")
        payload = fetch_json(str(target.external_id))
        return normalize_fotmob_heavy(payload)
    return fetch
