"""Phase 3 live-source latency shadow benchmark.

Measures candidate lightweight live sources without changing source priority.
HKJC remains eligibility authority; callers must provide already-authorised,
persistently VERIFIED identity rows. The benchmark never fuzzy-rematches and
never promotes a source to production primary.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping

Fetch = Callable[[], Mapping[str, Any]]


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int((len(ordered) - 1) * .95 + .999999)))]


def _age_seconds(value: Any, now: datetime) -> float | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        observed = datetime.fromisoformat(text)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return max(0.0, (now - observed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Candidate:
    name: str
    fetch: Fetch


def benchmark_sources(
    candidates: Iterable[Candidate], *, samples: int = 3,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Measure shadow sources independently; never select a production primary.

    Fetch payload contract: ``rows`` contains only rows already joined by a
    persistent VERIFIED identity; optional ``source_updated_at`` represents the
    source timestamp. A candidate request may represent one multi-match board.
    """
    if samples < 1:
        raise ValueError("samples must be >= 1")
    clock = now or datetime.now(timezone.utc)
    results: dict[str, Any] = {}
    for candidate in candidates:
        latencies: list[float] = []
        ages: list[float] = []
        requests = failures = mapped = unmapped = collisions = live = 0
        for _ in range(samples):
            started = perf_counter()
            try:
                payload = candidate.fetch()
                latencies.append((perf_counter() - started) * 1000.0)
                requests += 1
                rows = payload.get("rows") or []
                mapped += sum(1 for r in rows if r.get("identity_status") == "VERIFIED")
                unmapped += int(payload.get("unmapped_rows", 0) or 0)
                collisions += int(payload.get("collision_rows", 0) or 0)
                live += sum(1 for r in rows if r.get("status") in {"LIVE", "IN_PLAY"})
                age = _age_seconds(payload.get("source_updated_at"), clock)
                if age is not None:
                    ages.append(age)
            except Exception:
                requests += 1
                failures += 1
        results[candidate.name] = {
            "samples": samples,
            "upstream_requests": requests,
            "request_failures": failures,
            "failure_rate": failures / requests if requests else 0.0,
            "median_latency_ms": median(latencies) if latencies else None,
            "p95_latency_ms": _p95(latencies),
            "median_source_age_seconds": median(ages) if ages else None,
            "p95_source_age_seconds": _p95(ages),
            "mapped_rows": mapped,
            "unmapped_rows": unmapped,
            "collision_rows": collisions,
            "live_rows": live,
            "identity_match_rate": mapped / (mapped + unmapped + collisions) if (mapped + unmapped + collisions) else None,
        }
    return {
        "mode": "SHADOW_ONLY",
        "production_primary_changed": False,
        "measured_at": clock.isoformat(),
        "sources": results,
    }
