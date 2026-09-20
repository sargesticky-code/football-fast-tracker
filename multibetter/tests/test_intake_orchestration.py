from multibetter.scripts.summarize_intake import SOURCES


def test_intake_summary_tracks_all_six_sources():
    assert SOURCES == ("FRB", "ACC", "BCL", "FST", "PRE", "STA")
