from multibetter.intake.accumulator import _pair_matches_targets


def test_acc_route_filter_uses_oriented_forebet_pair():
    targets = [("Manchester City", "Sunderland")]

    assert _pair_matches_targets(
        "Man City",
        "Sunderland",
        targets,
    )
    assert not _pair_matches_targets(
        "Sunderland",
        "Manchester City",
        targets,
    )


def test_acc_route_filter_rejects_unrelated_fixture():
    targets = [("Manchester City", "Sunderland")]

    assert not _pair_matches_targets(
        "Chelsea",
        "Everton",
        targets,
    )
