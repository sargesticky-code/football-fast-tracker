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
    assert matched is rows[0]


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
