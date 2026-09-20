from multibetter.sources.github_multi import (
    group_sources_around_forebet,
    upstream_style_match,
)


FOREBET = {
    "DATE": "20/09/2026",
    "TIME": "21:00",
    "HOME TEAM": "Manchester City",
    "AWAY TEAM": "Sunderland",
    "HOME PER": "58",
    "DRAW PER": "25",
    "AWAY PER": "17",
    "OVER 2.5": "53",
    "UNDER 2.5": "47",
    "BTS": "47",
    "OTS": "53",
    "NAME": "Forebet",
}


def test_upstream_matcher_reuses_team_similarity_and_time_window():
    rows = [
        {
            "DATE": "20/09/2026",
            "TIME": "20:00",
            "HOME TEAM": "Man City",
            "AWAY TEAM": "Sunderland AFC",
            "NAME": "BCL",
        }
    ]
    matched = upstream_style_match(
        rows,
        target_home="Manchester City",
        target_away="Sunderland",
        target_time="21:00",
        target_date="20/09/2026",
        similarity_threshold=55,
    )
    assert matched["HOME TEAM"] == rows[0]["HOME TEAM"]
    assert matched["__MB_MATCH_QUALITY"] in {"HIGH", "GOOD", "REVIEW"}


def test_group_uses_forebet_as_anchor_not_hkjc():
    sources = {
        "BCL": [
            {
                "DATE": "20/09/2026",
                "TIME": "21:00",
                "HOME TEAM": "Manchester City FC",
                "AWAY TEAM": "Sunderland",
                "HOME PER": "61",
                "DRAW PER": "22",
                "AWAY PER": "17",
                "NAME": "BCL",
            }
        ],
        "STA": [
            {
                "DATE": "20/09/2026",
                "TIME": "21:00",
                "HOME TEAM": "Manchester City",
                "AWAY TEAM": "Sunderland",
                "HOME PER": "60",
                "DRAW PER": "23",
                "AWAY PER": "17",
                "NAME": "STA",
            }
        ],
    }

    grouped = group_sources_around_forebet(FOREBET, sources)

    assert grouped.github_forebet_home == "Manchester City"
    assert grouped.github_forebet_away == "Sunderland"
    assert [p.source for p in grouped.predictions] == ["FRB", "BCL", "STA"]
    assert grouped.predictions[1].home == "Manchester City FC"


def test_wrong_date_is_not_grouped():
    sources = {
        "BCL": [
            {
                "DATE": "19/09/2026",
                "TIME": "21:00",
                "HOME TEAM": "Manchester City",
                "AWAY TEAM": "Sunderland",
                "NAME": "BCL",
            }
        ]
    }
    grouped = group_sources_around_forebet(FOREBET, sources)
    assert [p.source for p in grouped.predictions] == ["FRB"]


def test_date_formats_are_normalized_across_sources():
    rows = [
        {
            "DATE": "2026-09-20",
            "TIME": "20:00",
            "HOME TEAM": "Manchester City",
            "AWAY TEAM": "Sunderland",
            "NAME": "STA",
        },
        {
            "DATE": "20/09/26",
            "TIME": "20:00",
            "HOME TEAM": "Manchester City",
            "AWAY TEAM": "Sunderland",
            "NAME": "FST",
        },
    ]

    sta = upstream_style_match(
        [rows[0]],
        target_home="Manchester City",
        target_away="Sunderland",
        target_time="21:00",
        target_date="20/09/2026",
    )
    fst = upstream_style_match(
        [rows[1]],
        target_home="Manchester City",
        target_away="Sunderland",
        target_time="21:00",
        target_date="20/09/2026",
    )

    assert sta["HOME TEAM"] == rows[0]["HOME TEAM"]
    assert fst["HOME TEAM"] == rows[1]["HOME TEAM"]


def test_unpadded_time_is_normalized():
    rows = [
        {
            "DATE": "20/09/2026",
            "TIME": "0:00",
            "HOME TEAM": "Manchester City",
            "AWAY TEAM": "Sunderland",
            "NAME": "BCL",
        }
    ]
    matched = upstream_style_match(
        rows,
        target_home="Manchester City",
        target_away="Sunderland",
        target_time="00:00",
        target_date="20/09/2026",
    )
    assert matched["HOME TEAM"] == rows[0]["HOME TEAM"]


def test_grouped_predictions_keep_match_quality():
    sources = {
        "BCL": [
            {
                "DATE": "20/09/2026",
                "TIME": "21:00",
                "HOME TEAM": "Manchester City FC",
                "AWAY TEAM": "Sunderland",
                "HOME PER": "61",
                "DRAW PER": "22",
                "AWAY PER": "17",
                "NAME": "BCL",
            }
        ]
    }
    grouped = group_sources_around_forebet(FOREBET, sources)
    assert grouped.predictions[0].source == "FRB"
    assert grouped.predictions[0].match_quality == "HIGH"
    assert grouped.predictions[1].match_similarity is not None
    assert grouped.predictions[1].match_quality in {"HIGH", "GOOD", "REVIEW"}


def test_current_normalized_mode_can_require_exact_time():
    rows = [
        {
            "DATE": "20/09/2026",
            "TIME": "20:00",
            "HOME TEAM": "Manchester City",
            "AWAY TEAM": "Sunderland",
            "NAME": "BCL",
        }
    ]
    matched = upstream_style_match(
        rows,
        target_home="Manchester City",
        target_away="Sunderland",
        target_time="21:00",
        target_date="20/09/2026",
        time_tolerance_hours=0,
    )
    assert matched is None
