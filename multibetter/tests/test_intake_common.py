import csv
from datetime import date
from pathlib import Path

from multibetter.intake.common import (
    base_row,
    local_fixture_to_utc,
    merge_rows,
    parse_date_any,
    preserve_last_good,
    utc_from_hkt,
)
from multibetter.intake.forebet_feed import collect_forebet_from_our_feed


def test_hkt_is_normalized_to_utc():
    dt = utc_from_hkt("2026-09-20 21:00")
    assert dt.isoformat() == "2026-09-20T13:00:00"


def test_merge_keeps_oriented_pair_and_combines_markets():
    a = base_row(
        source="X",
        match_date=date(2026, 9, 20),
        match_time_utc="13:00",
        home="Home",
        away="Away",
    )
    a["HOME PER"], a["DRAW PER"], a["AWAY PER"] = "50", "30", "20"
    b = base_row(
        source="X",
        match_date=date(2026, 9, 20),
        match_time_utc="13:00",
        home="Home",
        away="Away",
    )
    b["OVER 2.5"], b["UNDER 2.5"] = "60", "40"
    rows = merge_rows([a, b])
    assert len(rows) == 1
    assert rows[0]["HOME TEAM"] == "Home"
    assert rows[0]["AWAY TEAM"] == "Away"
    assert rows[0]["OVER 2.5"] == "60"
    assert rows[0]["1X PER"] == "80"


def test_empty_snapshot_does_not_overwrite_last_good(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text("old-data\n", encoding="utf-8")
    wrote = preserve_last_good(path, [])
    assert not wrote
    assert path.read_text(encoding="utf-8") == "old-data\n"


def test_our_forebet_becomes_utc_anchor(tmp_path):
    current = tmp_path / "forebet_current.csv"
    with current.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "match_date", "kickoff_text", "league_short", "home_team",
                "away_team", "prob_home", "prob_draw", "prob_away",
                "prob_over25", "prob_under25", "forebet_detail_url",
                "hkjc_event_id", "hkjc_kickoff_hkt",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "match_date": "2026-09-20",
            "kickoff_text": "20/09/2026 15:00",
            "league_short": "EPL",
            "home_team": "Manchester City",
            "away_team": "Sunderland",
            "prob_home": "60",
            "prob_draw": "22",
            "prob_away": "18",
            "prob_over25": "65",
            "prob_under25": "35",
            "forebet_detail_url": "https://example.test/match",
            "hkjc_event_id": "FB1",
            "hkjc_kickoff_hkt": "2026-09-20 21:00",
        })

    rows = collect_forebet_from_our_feed(
        current,
        target_dates=[date(2026, 9, 20)],
    )
    assert len(rows) == 1
    assert rows[0]["TIME"] == "13:00"
    assert rows[0]["SOURCE_TIME"] == "15:00"
    assert rows[0]["LEAGUE"] == "EPL"
    assert rows[0]["HOME TEAM"] == "Manchester City"
    assert rows[0]["AWAY TEAM"] == "Sunderland"


def test_provider_local_times_normalize_to_same_utc_clock():
    london = local_fixture_to_utc(
        date(2026, 9, 20), "14:00", "Europe/London"
    )
    berlin = local_fixture_to_utc(
        date(2026, 9, 20), "15:00", "Europe/Berlin"
    )
    assert london == (date(2026, 9, 20), "13:00")
    assert berlin == (date(2026, 9, 20), "13:00")


def test_parse_date_any_extracts_iso_date_from_detail_text():
    assert parse_date_any("Date 2026-09-20 14:00") == date(2026, 9, 20)
