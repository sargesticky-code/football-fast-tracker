from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from multibetter.models import MultiSourceFixture, SourcePrediction


UPSTREAM_DEFAULT_WEIGHTS = {
    "ACC": 0.8,
    "BCL": 1.0,
    "FST": 0.9,
    "FRB": 1.4,
    "PRE": 1.1,
    "STA": 1.2,
}


def build_multi_fixture(
    *,
    kickoff: datetime,
    github_forebet_home: str,
    github_forebet_away: str,
    github_forebet_competition: str | None = None,
    predictions: Iterable[SourcePrediction] = (),
    external_fixture_id: str | None = None,
) -> MultiSourceFixture:
    """Create the Multibetter boundary object from GitHub multi-source output."""

    return MultiSourceFixture(
        kickoff=kickoff,
        github_forebet_home=github_forebet_home,
        github_forebet_away=github_forebet_away,
        github_forebet_competition=github_forebet_competition,
        predictions=tuple(predictions),
        external_fixture_id=external_fixture_id,
    )


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio() * 100.0


def _time_variants(value: str) -> set[str]:
    dt = datetime.strptime(value, "%H:%M")
    return {
        (dt - timedelta(hours=1)).strftime("%H:%M"),
        dt.strftime("%H:%M"),
        (dt + timedelta(hours=1)).strftime("%H:%M"),
    }


def upstream_style_match(
    rows: Sequence[Mapping[str, object]],
    *,
    target_home: str,
    target_away: str,
    target_time: str,
    target_date: str | None = None,
    similarity_threshold: float = 55.0,
) -> Mapping[str, object] | None:
    """Reuse the public GitHub project's matching idea, anchored on Forebet.

    The upstream project filters each source by:
    - home-team SequenceMatcher score >= threshold
    - away-team SequenceMatcher score >= threshold
    - time equal to target time or +/- 1 hour

    Multibetter adds an optional exact DATE guard when both sides provide DATE.
    This reduces false positives without adding a new team-alias system.
    """

    valid_times = _time_variants(target_time)
    candidates: list[tuple[float, Mapping[str, object]]] = []

    for row in rows:
        home = str(row.get("HOME TEAM", "") or "")
        away = str(row.get("AWAY TEAM", "") or "")
        time_value = str(row.get("TIME", "") or "")
        date_value = str(row.get("DATE", "") or "")

        if not home or not away or time_value not in valid_times:
            continue
        if target_date and date_value and date_value != target_date:
            continue

        hs = _similarity(home, target_home)
        aws = _similarity(away, target_away)
        if hs < similarity_threshold or aws < similarity_threshold:
            continue

        candidates.append(((hs + aws) / 2.0, row))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _as_float(row: Mapping[str, object], key: str) -> float | None:
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def source_row_to_prediction(
    row: Mapping[str, object],
    *,
    source: str,
) -> SourcePrediction:
    probs: dict[str, float] = {}
    column_map = {
        "home": "HOME PER",
        "draw": "DRAW PER",
        "away": "AWAY PER",
        "over25": "OVER 2.5",
        "under25": "UNDER 2.5",
        "btts_yes": "BTS",
        "btts_no": "OTS",
    }

    for key, column in column_map.items():
        value = _as_float(row, column)
        if value is not None:
            probs[key] = value

    return SourcePrediction(
        source=source,
        kickoff=None,
        competition=None,
        home=str(row.get("HOME TEAM", "") or ""),
        away=str(row.get("AWAY TEAM", "") or ""),
        probabilities=probs,
        market_label=str(row.get("NAME", "") or source),
        source_kickoff_text=str(row.get("TIME", "") or "") or None,
    )


def group_sources_around_forebet(
    forebet_row: Mapping[str, object],
    source_tables: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    similarity_threshold: float = 55.0,
    github_forebet_competition: str | None = None,
) -> MultiSourceFixture:
    """Build one grouped fixture using GitHub Forebet as the anchor.

    This is the adaptation layer the user approved:
    external source rows -> upstream matcher -> GitHub Forebet fixture -> OUR Forebet.
    No source-to-HKJC alias work is performed.
    """

    home = str(forebet_row.get("HOME TEAM", "") or "")
    away = str(forebet_row.get("AWAY TEAM", "") or "")
    time_value = str(forebet_row.get("TIME", "") or "")
    date_value = str(forebet_row.get("DATE", "") or "")

    if not home or not away or not time_value or not date_value:
        raise ValueError("Forebet anchor requires DATE, TIME, HOME TEAM and AWAY TEAM")

    parsed_date = None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            parsed_date = datetime.strptime(date_value, fmt).date()
            break
        except ValueError:
            pass
    if parsed_date is None:
        raise ValueError(f"Unsupported Forebet DATE format: {date_value}")

    kickoff_time = datetime.strptime(time_value, "%H:%M").time()
    kickoff = datetime.combine(parsed_date, kickoff_time)

    predictions: list[SourcePrediction] = []

    # Include the Forebet row itself.
    predictions.append(source_row_to_prediction(forebet_row, source="FRB"))

    for source, rows in source_tables.items():
        if source == "FRB":
            continue
        matched = upstream_style_match(
            rows,
            target_home=home,
            target_away=away,
            target_time=time_value,
            target_date=date_value,
            similarity_threshold=similarity_threshold,
        )
        if matched is not None:
            predictions.append(source_row_to_prediction(matched, source=source))

    external_fixture_id = f"{date_value}|{time_value}|{home}|{away}"

    return build_multi_fixture(
        kickoff=kickoff,
        github_forebet_home=home,
        github_forebet_away=away,
        github_forebet_competition=github_forebet_competition,
        predictions=predictions,
        external_fixture_id=external_fixture_id,
    )
