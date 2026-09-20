from datetime import datetime

from multibetter.aliasing.cache import AliasCacheRow
from multibetter.pipeline.current import build_current


OUR = [
    {
        "kickoff_text": "20/09/2026 21:00",
        "league_short": "EPL",
        "home_team": "Manchester City",
        "away_team": "Sunderland",
        "hkjc_event_id": "FB1",
        "hkjc_home_team": "Man City HKJC",
        "hkjc_away_team": "Sunderland HKJC",
        "hkjc_kickoff_hkt": "2026-09-21 05:00",
    },
    {
        "kickoff_text": "20/09/2026 21:00",
        "league_short": "EPL",
        "home_team": "Bournemouth",
        "away_team": "Liverpool",
        "hkjc_event_id": "FB2",
        "hkjc_home_team": "Bournemouth HKJC",
        "hkjc_away_team": "Liverpool HKJC",
        "hkjc_kickoff_hkt": "2026-09-21 05:00",
    },
]


def sources(home="Man City", away="Sunderland AFC"):
    return {
        "FRB": [
            {
                "DATE": "20/09/2026",
                "TIME": "21:00",
                "LEAGUE": "EPL",
                "HOME TEAM": home,
                "AWAY TEAM": away,
                "HOME PER": "55",
                "DRAW PER": "25",
                "AWAY PER": "20",
                "OVER 2.5": "60",
                "UNDER 2.5": "40",
                "BTS": "45",
                "OTS": "55",
                "NAME": "Forebet",
            }
        ],
        "BCL": [
            {
                "DATE": "2026-09-20",
                "TIME": "21:00",
                "HOME TEAM": "Manchester City",
                "AWAY TEAM": "Sunderland",
                "HOME PER": "60",
                "DRAW PER": "22",
                "AWAY PER": "18",
                "OVER 2.5": "65",
                "UNDER 2.5": "35",
                "BTS": "50",
                "OTS": "50",
                "NAME": "BCL",
            }
        ],
    }


def test_first_run_learns_alias_and_outputs_event():
    result = build_current(
        our_forebet_rows=OUR,
        source_tables=sources(),
        cache_rows=[],
        observed_at=datetime(2026, 9, 20, 8, 0),
    )
    row = result.rows[0]
    assert row["hkjc_event_id"] == "FB1"
    assert row["match_status"] == "DETERMINISTIC_TEAM_PAIR"
    assert result.learned_alias_count == 2
    assert {x.alias for x in result.alias_cache} == {"Man City", "Sunderland AFC"}


def test_second_run_uses_alias_cache():
    cache = [
        AliasCacheRow("Man City", "Manchester City"),
        AliasCacheRow("Sunderland AFC", "Sunderland"),
    ]
    result = build_current(
        our_forebet_rows=OUR,
        source_tables=sources(),
        cache_rows=cache,
        observed_at=datetime(2026, 9, 21, 8, 0),
    )
    row = result.rows[0]
    assert row["match_status"] == "FAST_ALIAS"
    assert result.learned_alias_count == 0


def test_home_away_reversal_does_not_learn():
    result = build_current(
        our_forebet_rows=OUR,
        source_tables=sources(
            home="Sunderland AFC",
            away="Man City",
        ),
        cache_rows=[],
        observed_at=datetime(2026, 9, 20, 8, 0),
    )
    row = result.rows[0]
    assert row["match_status"] in {"AMBIGUOUS", "CONFLICT"}
    assert result.learned_alias_count == 0


def test_consensus_is_emitted_from_high_quality_sources():
    result = build_current(
        our_forebet_rows=OUR,
        source_tables=sources(),
        cache_rows=[],
        observed_at=datetime(2026, 9, 20, 8, 0),
    )
    row = result.rows[0]
    assert row["source_count_total"] == 2
    assert row["consensus_home"] > 0
    assert row["consensus_over25"] > 0


def test_our_fixture_clock_uses_hkjc_hkt_as_utc_reference():
    from multibetter.pipeline.current import load_our_forebet_fixtures

    fixtures, _ = load_our_forebet_fixtures(OUR)
    assert fixtures[0].kickoff.isoformat() == "2026-09-20T21:00:00"


def test_stale_preserved_source_is_not_loaded(tmp_path):
    import json
    from multibetter.pipeline.current import load_source_tables

    source_dir = tmp_path / "current"
    health_dir = tmp_path / "health"
    source_dir.mkdir()
    health_dir.mkdir()

    (source_dir / "forebet.csv").write_text(
        "DATE,TIME,HOME TEAM,AWAY TEAM\n20/09/2026,13:00,A,B\n",
        encoding="utf-8",
    )
    (source_dir / "betclan.csv").write_text(
        "DATE,TIME,HOME TEAM,AWAY TEAM\n20/09/2026,13:00,A,B\n",
        encoding="utf-8",
    )
    (health_dir / "frb.json").write_text(
        json.dumps({"status": "OK"}),
        encoding="utf-8",
    )
    (health_dir / "bcl.json").write_text(
        json.dumps({"status": "KEEP_LAST_GOOD"}),
        encoding="utf-8",
    )

    tables = load_source_tables(source_dir, health_dir=health_dir)
    assert "FRB" in tables
    assert "BCL" not in tables


def test_built_at_is_sheet_friendly_local_timestamp_text():
    result = build_current(
        our_forebet_rows=OUR,
        source_tables=sources(),
        cache_rows=[],
        observed_at=datetime(2026, 9, 20, 8, 0),
    )
    assert result.rows[0]["built_at"] == "2026-09-20 08:00:00"
