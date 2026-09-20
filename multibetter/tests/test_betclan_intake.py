from multibetter.intake.betclan import _fixture_slug, _targeted_links


def test_betclan_detail_links_are_scoped_to_current_targets():
    links = [
        "https://www.betclan.com/predictionsdetails/football/1/man-city-v-sunderland-prediction-h2h-tip-and-match-preview/",
        "https://www.betclan.com/predictionsdetails/football/2/chelsea-v-everton-prediction-h2h-tip-and-match-preview/",
    ]
    selected = _targeted_links(
        links,
        [("Manchester City", "Sunderland")],
    )
    assert selected == [links[0]]
    assert _fixture_slug(links[0]) == "man city vs sunderland"
