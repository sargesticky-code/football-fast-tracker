from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from multibetter.aliasing.cache import (
    AliasCacheRow,
    merge_learned_aliases,
    touch_aliases,
)
from multibetter.consensus.engine import weighted_consensus
from multibetter.matching.fixture_resolver import (
    FixtureResolveStatus,
    build_fixture_index,
    build_time_index,
    resolve_fixture_cache_first,
)
from multibetter.models import CanonicalFixture, Market, MultiSourceFixture
from multibetter.sources.github_multi import (
    UPSTREAM_DEFAULT_WEIGHTS,
    group_sources_around_forebet,
)


SOURCE_FILES = {
    "ACC": "accumulator.csv",
    "BCL": "betclan.csv",
    "FST": "footballsupertips.csv",
    "FRB": "forebet.csv",
    "PRE": "prematips.csv",
    "STA": "statarea.csv",
}


@dataclass(frozen=True)
class CurrentBuildResult:
    rows: tuple[dict[str, object], ...]
    alias_cache: tuple[AliasCacheRow, ...]
    learned_alias_count: int
    status_counts: Mapping[str, int]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _parse_our_forebet_kickoff(row: Mapping[str, str]) -> datetime | None:
    """Return canonical naive UTC kickoff.

    HKJC HKT is the strongest cross-source clock we already own. Convert it to
    UTC so GMT/UTC prediction providers and our fixture resolver use one clock.
    """
    value = (row.get("hkjc_kickoff_hkt") or "").strip()
    if value:
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(value[:19], fmt)
                break
            except ValueError:
                pass
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)

    # Legacy fallback for rows without HKJC kickoff.
    value = (row.get("kickoff_text") or "").strip()
    for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M"):
        if value:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
    return None


def load_our_forebet_fixtures(
    rows: Iterable[Mapping[str, str]],
) -> tuple[list[CanonicalFixture], dict[str, Mapping[str, str]]]:
    fixtures: list[CanonicalFixture] = []
    raw_by_event: dict[str, Mapping[str, str]] = {}

    for row in rows:
        event_id = (row.get("hkjc_event_id") or "").strip()
        home = (row.get("home_team") or "").strip()
        away = (row.get("away_team") or "").strip()
        kickoff = _parse_our_forebet_kickoff(row)

        if not event_id or not home or not away or kickoff is None:
            continue

        competition = (
            (row.get("league_short") or "").strip()
            or (row.get("hkjc_league") or "").strip()
        )
        fixture = CanonicalFixture(
            event_id=event_id,
            kickoff=kickoff,
            competition=competition,
            hkjc_home=(row.get("hkjc_home_team") or "").strip() or home,
            hkjc_away=(row.get("hkjc_away_team") or "").strip() or away,
            forebet_home=home,
            forebet_away=away,
            forebet_competition=(row.get("league_short") or "").strip() or None,
        )
        fixtures.append(fixture)
        raw_by_event[event_id] = row

    return fixtures, raw_by_event


def load_source_tables(
    source_dir: Path,
    *,
    health_dir: Path | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Load only fresh source snapshots when health metadata is supplied.

    Last-good CSVs are intentionally preserved on scrape failure, but a stale
    preserved file must not silently enter the current consensus.
    """
    result: dict[str, list[dict[str, str]]] = {}
    for source, filename in SOURCE_FILES.items():
        if health_dir is not None:
            health_path = health_dir / f"{source.lower()}.json"
            if not health_path.exists():
                continue
            try:
                health = json.loads(health_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if health.get("status") != "OK":
                continue

        rows = read_csv_rows(source_dir / filename)
        if rows:
            result[source] = rows
    return result


def alias_map(rows: Iterable[AliasCacheRow]) -> dict[str, str]:
    return {row.alias: row.target for row in rows}


def _quality_confidence(value: str | None) -> float:
    if value == "HIGH":
        return 1.0
    if value == "GOOD":
        return 0.90
    if value == "REVIEW":
        return 0.75
    return 1.0


def _market_weights(market: Market):
    return {
        (source, market): weight
        for source, weight in UPSTREAM_DEFAULT_WEIGHTS.items()
    }


def _consensus(multi: MultiSourceFixture, market: Market):
    if market == Market.HDA:
        keys = {"home", "draw", "away"}
    elif market == Market.GOALS:
        keys = {"over25", "under25"}
    elif market == Market.BTTS:
        keys = {"btts_yes", "btts_no"}
    else:
        return None

    rows = []
    for prediction in multi.predictions:
        probs = {
            key: value
            for key, value in prediction.probabilities.items()
            if key in keys
        }
        if not probs:
            continue
        rows.append(
            (
                prediction.source,
                probs,
                _quality_confidence(prediction.match_quality),
            )
        )

    return weighted_consensus(
        rows,
        market=market,
        source_weights=_market_weights(market),
        min_match_confidence=0.85,
    )


def _competition_from_forebet_row(row: Mapping[str, str]) -> str | None:
    for key in ("LEAGUE", "COMPETITION", "TOURNAMENT"):
        value = (row.get(key) or "").strip()
        if value:
            return value
    return None


def build_current(
    *,
    our_forebet_rows: Iterable[Mapping[str, str]],
    source_tables: Mapping[str, list[dict[str, str]]],
    cache_rows: Iterable[AliasCacheRow] = (),
    observed_at: datetime | None = None,
) -> CurrentBuildResult:
    observed_at = observed_at or datetime.now()
    fixtures, raw_by_event = load_our_forebet_fixtures(our_forebet_rows)

    fixture_index = build_fixture_index(fixtures)
    time_index = build_time_index(fixtures)

    cache_state = tuple(cache_rows)
    learned_total = 0
    output: list[dict[str, object]] = []
    status_counts: dict[str, int] = {}

    forebet_rows = source_tables.get("FRB", [])

    for forebet_row in forebet_rows:
        try:
            multi = group_sources_around_forebet(
                forebet_row,
                source_tables,
                github_forebet_competition=_competition_from_forebet_row(
                    forebet_row
                ),
            )
        except ValueError as exc:
            status = "INVALID_SOURCE_ROW"
            status_counts[status] = status_counts.get(status, 0) + 1
            output.append(
                {
                    "external_fixture_id": "",
                    "match_status": status,
                    "match_reason": str(exc),
                    "github_forebet_home": forebet_row.get("HOME TEAM", ""),
                    "github_forebet_away": forebet_row.get("AWAY TEAM", ""),
                }
            )
            continue

        result = resolve_fixture_cache_first(
            multi,
            fixtures,
            verified_aliases=alias_map(cache_state),
            fixture_index=fixture_index,
            time_index=time_index,
        )

        status = result.status.value
        status_counts[status] = status_counts.get(status, 0) + 1

        learned_labels: list[str] = []

        if result.status == FixtureResolveStatus.FAST_ALIAS:
            cache_aliases = alias_map(cache_state)
            aliases_used = [
                name
                for name in (
                    multi.github_forebet_home,
                    multi.github_forebet_away,
                )
                if name in cache_aliases
            ]
            if aliases_used:
                cache_state = touch_aliases(
                    cache_state,
                    aliases_used,
                    observed_at=observed_at,
                )

        if result.learned_aliases:
            cache_state = merge_learned_aliases(
                cache_state,
                result.learned_aliases,
                observed_at=observed_at,
            )
            learned_total += len(result.learned_aliases)
            learned_labels = [
                f"{item.alias}->{item.target}"
                for item in result.learned_aliases
            ]

        fixture = result.fixture
        raw = raw_by_event.get(fixture.event_id, {}) if fixture else {}

        hda = _consensus(multi, Market.HDA)
        goals = _consensus(multi, Market.GOALS)
        btts = _consensus(multi, Market.BTTS)

        source_names = [p.source for p in multi.predictions]
        accepted_source_names = [
            p.source
            for p in multi.predictions
            if _quality_confidence(p.match_quality) >= 0.85
        ]

        row: dict[str, object] = {
            "built_at": observed_at.isoformat(),
            "external_fixture_id": multi.external_fixture_id or "",
            "github_forebet_date": multi.kickoff.date().isoformat(),
            "github_forebet_time": multi.kickoff.strftime("%H:%M"),
            "github_forebet_league": multi.github_forebet_competition or "",
            "github_forebet_home": multi.github_forebet_home,
            "github_forebet_away": multi.github_forebet_away,
            "home_away_explicit": int(multi.home_away_explicit),
            "match_status": status,
            "match_reason": result.reason,
            "candidate_count": result.candidate_count,
            "hkjc_event_id": fixture.event_id if fixture else "",
            "our_forebet_home": fixture.forebet_home if fixture else "",
            "our_forebet_away": fixture.forebet_away if fixture else "",
            "hkjc_home": fixture.hkjc_home if fixture else "",
            "hkjc_away": fixture.hkjc_away if fixture else "",
            "hkjc_kickoff_hkt": raw.get("hkjc_kickoff_hkt", "") if raw else "",
            "source_count_total": len(source_names),
            "sources_total": "+".join(source_names),
            "source_count_consensus": len(accepted_source_names),
            "sources_consensus": "+".join(accepted_source_names),
            "learned_alias_count": len(learned_labels),
            "learned_aliases": "|".join(learned_labels),
        }

        if hda and hda.probabilities:
            row.update(
                {
                    "consensus_home": round(
                        hda.probabilities.get("home", 0.0) * 100, 2
                    ),
                    "consensus_draw": round(
                        hda.probabilities.get("draw", 0.0) * 100, 2
                    ),
                    "consensus_away": round(
                        hda.probabilities.get("away", 0.0) * 100, 2
                    ),
                }
            )

        if goals and goals.probabilities:
            row.update(
                {
                    "consensus_over25": round(
                        goals.probabilities.get("over25", 0.0) * 100, 2
                    ),
                    "consensus_under25": round(
                        goals.probabilities.get("under25", 0.0) * 100, 2
                    ),
                }
            )

        if btts and btts.probabilities:
            row.update(
                {
                    "consensus_btts_yes": round(
                        btts.probabilities.get("btts_yes", 0.0) * 100, 2
                    ),
                    "consensus_btts_no": round(
                        btts.probabilities.get("btts_no", 0.0) * 100, 2
                    ),
                }
            )

        output.append(row)

    return CurrentBuildResult(
        rows=tuple(output),
        alias_cache=cache_state,
        learned_alias_count=learned_total,
        status_counts=status_counts,
    )
