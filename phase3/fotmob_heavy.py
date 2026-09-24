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
        if home is None and away is None and isinstance(value.get("stats"), (list, tuple)):
            return _pair(value["stats"])
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        home, away = _number(value[0]), _number(value[1])
    else:
        return None
    if home is None and away is None:
        return None
    return {"home": home, "away": away}


def _norm_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


_ALIASES = {
    "xg": ("expected goals", "expected goals (xg)", "expected_goals", "expectedGoals", "xG", "xg"),
    "shots": ("total shots", "total_shots", "totalShots", "shots"),
    "shots_on_target": ("shots on target", "shots_on_target", "shotsOnTarget"),
    "possession": ("ball possession", "possession", "ballPossession"),
    "box_touches": ("touches in opposition box", "touches_in_opposition_box", "touchesInOppositionBox", "boxTouches"),
    "big_chances": ("big chances", "big_chances", "bigChances"),
    "corners": ("corners", "corner kicks", "cornerKicks"),
}


def _stats_root(payload: dict[str, Any]) -> Any:
    content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    stats = payload.get("stats") or content.get("stats") or {}
    if not isinstance(stats, dict):
        return stats
    periods = stats.get("Periods") or stats.get("periods")
    if isinstance(periods, dict):
        all_period = periods.get("All") or periods.get("all")
        if isinstance(all_period, dict):
            return all_period.get("stats", all_period)
        if all_period is not None:
            return all_period
    return stats


def _walk_stats(node: Any):
    """Yield every observed stat label -> value pair from known FotMob shapes.

    FotMob presentation objects may carry both a machine ``key`` and a human
    ``title``.  They are not guaranteed to be identical (and historic payloads
    contain spelling/casing differences), so preserve both labels whenever the
    object itself contains an observed home/away pair.  This avoids coupling
    Layer 6 coverage to an unstable presentation key while still never guessing
    a value.
    """
    if isinstance(node, dict):
        labels = []
        for label_key in ("key", "title", "name"):
            label = node.get(label_key)
            if label is not None and str(label) not in labels:
                labels.append(str(label))

        observed = None
        if "stats" in node:
            observed = node.get("stats")
        elif any(k in node for k in ("home", "away", "homeValue", "awayValue")):
            observed = node
        if _pair(observed) is not None:
            for label in labels:
                yield label, observed

        for key, value in node.items():
            if key not in {"key", "title", "name"}:
                # Flat FotMob payloads can expose the metric name as the dict key,
                # with the observed home/away pair in the value. Preserve that
                # parent key before descending into presentation wrappers.
                if isinstance(value, (dict, list, tuple)):
                    if _pair(value) is not None:
                        yield str(key), value
                else:
                    yield str(key), value
                yield from _walk_stats(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk_stats(item)


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if isinstance(value, (list, dict)) and value:
            return value
    return None


def normalize_fotmob_heavy(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return observed heavy fields only; absent fields remain None."""
    payload = payload or {}
    lookup: dict[str, Any] = {}
    for key, value in _walk_stats(_stats_root(payload)):
        lookup.setdefault(_norm_key(key), value)

    out: dict[str, Any] = {}
    for field, aliases in _ALIASES.items():
        pair = None
        for alias in aliases:
            pair = _pair(lookup.get(_norm_key(alias)))
            if pair is not None:
                break
        out[field] = pair

    content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    facts = content.get("matchFacts") if isinstance(content.get("matchFacts"), dict) else {}
    facts_events = facts.get("events")
    if isinstance(facts_events, dict):
        facts_events = facts_events.get("events") or facts_events.get("incidents")
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    events = _first_nonempty(payload.get("events"), facts_events, header.get("events"))

    content_momentum = content.get("momentum")
    facts_momentum = facts.get("momentum")
    momentum = _first_nonempty(payload.get("momentum"), content_momentum, facts_momentum)
    if isinstance(momentum, dict):
        main = momentum.get("main")
        if isinstance(main, dict) and isinstance(main.get("data"), list):
            momentum = main["data"]
        elif isinstance(momentum.get("data"), list):
            momentum = momentum["data"]

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
