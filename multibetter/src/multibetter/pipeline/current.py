from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

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
from multibetter.normalization.teams import normalize_text
from multibetter.sources.github_multi import (
    UPSTREAM_DEFAULT_WEIGHTS,
    group_sources_around_anchor,
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
    value = (
        row.get("hkjc_kickoff_hkt")
        or row.get("kickoff_hkt")
        or ""
    ).strip()
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


def _load_master_lookup(
    master_dir: Path | None,
    source: str,
) -> tuple[dict[str, dict[str, object]], set[str]]:
    if master_dir is None:
        return {}, set()
    path = master_dir / f"{source}.json"
    if not path.exists():
        return {}, set()
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}, set()

    blocked = {
        normalize_text(str(value))
        for value in body.get("blockedNames", [])
        if str(value).strip()
    }
    candidates: dict[str, list[dict[str, object]]] = {}
    for item in body.get("rows", []):
        source_name = str(item.get("source_name") or "").strip()
        canonical = str(item.get("hkjc_name_en") or "").strip()
        team_key = str(item.get("team_key") or "").strip()
        if not source_name or not canonical or not team_key:
            continue
        key = normalize_text(source_name)
        if not key or key in blocked:
            continue
        candidates.setdefault(key, []).append(item)

    verified = {
        key: items[0]
        for key, items in candidates.items()
        if len({str(x.get("team_key") or "") for x in items}) == 1
    }
    return verified, blocked


def _apply_master_lookup(
    rows: list[dict[str, str]],
    *,
    source: str,
    master_dir: Path | None,
) -> list[dict[str, str]]:
    verified, blocked = _load_master_lookup(master_dir, source)
    if not verified:
        return rows

    output: list[dict[str, str]] = []
    for raw in rows:
        row = dict(raw)
        for label in ("HOME TEAM", "AWAY TEAM"):
            original = str(row.get(label, "") or "").strip()
            if not original:
                continue
            key = normalize_text(original)
            if key in blocked:
                row[f"__MB_MASTER_{label.split()[0]}_BLOCKED"] = "1"
                continue
            hit = verified.get(key)
            if not hit:
                continue

            side = label.split()[0]
            row[f"__MB_RAW_{side}_TEAM"] = original
            row[f"__MB_MASTER_{side}_HIT"] = "1"
            row[f"__MB_MASTER_{side}_TEAM_KEY"] = str(hit.get("team_key") or "")
            row[label] = str(hit.get("hkjc_name_en") or original)
        output.append(row)
    return output


def load_source_tables(
    source_dir: Path,
    *,
    health_dir: Path | None = None,
    master_dir: Path | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Load only fresh source snapshots and canonicalize VERIFIED source names.

    Master lookup is the runtime hot path. Legacy similarity matching remains
    available only for names that are not yet safely VERIFIED.
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
            result[source] = _apply_master_lookup(
                rows,
                source=source,
                master_dir=master_dir,
            )
    return result



def load_hkjc_target_fixtures(
    rows: Iterable[Mapping[str, str]],
) -> tuple[list[CanonicalFixture], dict[str, Mapping[str, str]]]:
    """Build the canonical Multibetter universe directly from HKJC targets."""
    fixtures: list[CanonicalFixture] = []
    raw_by_event: dict[str, Mapping[str, str]] = {}

    for row in rows:
        event_id = (row.get("hkjc_event_id") or "").strip()
        home = (row.get("home_en") or row.get("home_team") or "").strip()
        away = (row.get("away_en") or row.get("away_team") or "").strip()
        kickoff = _parse_our_forebet_kickoff(row)
        if not event_id or not home or not away or kickoff is None:
            continue

        competition = (
            (row.get("league_zh") or "").strip()
            or (row.get("tournament") or "").strip()
            or (row.get("hkjc_league") or "").strip()
        )
        fixture = CanonicalFixture(
            event_id=event_id,
            kickoff=kickoff,
            competition=competition,
            hkjc_home=home,
            hkjc_away=away,
            forebet_home=home,
            forebet_away=away,
            forebet_competition=competition or None,
        )
        fixtures.append(fixture)
        raw_by_event[event_id] = row

    return fixtures, raw_by_event


def build_hkjc_anchored_current(
    *,
    hkjc_target_rows: Iterable[Mapping[str, str]],
    source_tables: Mapping[str, list[dict[str, str]]],
    cache_rows: Iterable[AliasCacheRow] = (),
    observed_at: datetime | None = None,
) -> CurrentBuildResult:
    """Build consensus for the full HKJC target universe.

    FRB is now one evidence member rather than the gatekeeper for fixture
    existence. Sources are matched only inside each HKJC date/time/home-away
    anchor using the same safe upstream matcher.
    """
    observed_at = observed_at or datetime.now(ZoneInfo("Asia/Hong_Kong"))
    fixtures, raw_by_event = load_hkjc_target_fixtures(hkjc_target_rows)
    output: list[dict[str, object]] = []

    for fixture in fixtures:
        raw = raw_by_event.get(fixture.event_id, {})
        anchor = {
            "DATE": fixture.kickoff.strftime("%d/%m/%Y"),
            "TIME": fixture.kickoff.strftime("%H:%M"),
            "LEAGUE": fixture.competition,
            "HOME TEAM": fixture.hkjc_home,
            "AWAY TEAM": fixture.hkjc_away,
        }
        multi = group_sources_around_anchor(
            anchor,
            source_tables,
            similarity_threshold=55.0,
            time_tolerance_hours=0,
            time_tolerance_minutes=5,
            external_fixture_id=fixture.event_id,
        )

        hda = _consensus(multi, Market.HDA)
        goals = _consensus(multi, Market.GOALS)
        btts = _consensus(multi, Market.BTTS)

        usable_predictions = [
            p for p in multi.predictions
            if bool(p.probabilities)
        ]
        source_names = [p.source for p in usable_predictions]
        accepted_source_names = [
            p.source
            for p in usable_predictions
            if _quality_confidence(p.match_quality) >= 0.85
        ]
        master_direct_sources = [
            p.source for p in usable_predictions if p.match_quality == "MASTER"
        ]

        identity_evidence = [
            {
                "source": p.source,
                "home": p.home,
                "away": p.away,
                "match_similarity": p.match_similarity,
                "match_quality": p.match_quality,
            }
            for p in multi.predictions
            if p.source in SOURCE_FILES and p.home and p.away
        ]

        row: dict[str, object] = {
            "built_at": observed_at.strftime("%Y-%m-%d %H:%M:%S"),
            "external_fixture_id": fixture.event_id,
            "github_forebet_date": fixture.kickoff.date().isoformat(),
            "github_forebet_time": fixture.kickoff.strftime("%H:%M"),
            "github_forebet_league": fixture.competition,
            "github_forebet_home": fixture.hkjc_home,
            "github_forebet_away": fixture.hkjc_away,
            "home_away_explicit": 1,
            "match_status": "HKJC_ANCHOR",
            "match_reason": "HKJC_AUTHORITY_FIXTURE",
            "candidate_count": len(source_names),
            "hkjc_event_id": fixture.event_id,
            "our_forebet_home": fixture.forebet_home,
            "our_forebet_away": fixture.forebet_away,
            "hkjc_home": fixture.hkjc_home,
            "hkjc_away": fixture.hkjc_away,
            "hkjc_kickoff_hkt": raw.get("kickoff_hkt", ""),
            "source_count_total": len(source_names),
            "sources_total": "+".join(source_names),
            "source_count_consensus": len(accepted_source_names),
            "sources_consensus": "+".join(accepted_source_names),
            "learned_alias_count": 0,
            "learned_aliases": "",
            "master_direct_source_count": len(master_direct_sources),
            "master_direct_sources": "+".join(master_direct_sources),
            "identity_evidence": json.dumps(identity_evidence, ensure_ascii=False),
        }

        if hda and hda.probabilities:
            row.update({
                "consensus_home": round(hda.probabilities.get("home", 0.0) * 100, 2),
                "consensus_draw": round(hda.probabilities.get("draw", 0.0) * 100, 2),
                "consensus_away": round(hda.probabilities.get("away", 0.0) * 100, 2),
            })
        if goals and goals.probabilities:
            row.update({
                "consensus_over25": round(goals.probabilities.get("over25", 0.0) * 100, 2),
                "consensus_under25": round(goals.probabilities.get("under25", 0.0) * 100, 2),
            })
        if btts and btts.probabilities:
            row.update({
                "consensus_btts_yes": round(btts.probabilities.get("btts_yes", 0.0) * 100, 2),
                "consensus_btts_no": round(btts.probabilities.get("btts_no", 0.0) * 100, 2),
            })

        output.append(row)

    return CurrentBuildResult(
        rows=tuple(output),
        alias_cache=tuple(cache_rows),
        learned_alias_count=0,
        status_counts={"HKJC_ANCHOR": len(output)},
    )


def alias_map(rows: Iterable[AliasCacheRow]) -> dict[str, str]:
    return {row.alias: row.target for row in rows}


def _quality_confidence(value: str | None) -> float:
    if value == "MASTER":
        return 1.0
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
    observed_at = observed_at or datetime.now(ZoneInfo("Asia/Hong_Kong"))
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
                time_tolerance_hours=0,
                time_tolerance_minutes=5,
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
            "built_at": observed_at.strftime("%Y-%m-%d %H:%M:%S"),
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
