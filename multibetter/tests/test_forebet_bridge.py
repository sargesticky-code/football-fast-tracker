from multibetter.matching.forebet_bridge import BridgeStatus, bridge_team_name


def test_exact_is_default():
    result = bridge_team_name("Manchester City", {"Manchester City", "Arsenal"})
    assert result.status == BridgeStatus.EXACT
    assert result.our_forebet_name == "Manchester City"


def test_verified_exception_alias_only():
    result = bridge_team_name(
        "Example FC Old",
        {"Example FC"},
        exception_aliases={"Example FC Old": "Example FC"},
    )
    assert result.status == BridgeStatus.ALIAS
    assert result.our_forebet_name == "Example FC"


def test_missing_reference_is_not_called_mismatch():
    result = bridge_team_name("World Club Not Yet Seen By HKJC", {"Arsenal"})
    assert result.status == BridgeStatus.OUR_REFERENCE_MISSING


def test_normalized_difference_requires_review_not_auto_accept():
    result = bridge_team_name("Atlético Madrid", {"Atletico Madrid"})
    assert result.status == BridgeStatus.CANDIDATE
    assert result.our_forebet_name == "Atletico Madrid"
