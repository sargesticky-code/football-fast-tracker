from multibetter.scripts.summarize_intake import SOURCES


def test_intake_summary_tracks_all_six_sources():
    assert SOURCES == ("FRB", "ACC", "BCL", "FST", "PRE", "STA")


def test_degraded_gate_requires_two_optional_sources():
    from multibetter.scripts import summarize_intake as module
    assert module.SOURCES == ("FRB", "ACC", "BCL", "FST", "PRE", "STA")
