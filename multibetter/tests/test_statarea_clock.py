from datetime import date

from multibetter.intake.statarea import (
    _apply_clock_offset,
    infer_statarea_clock_offset,
)


def test_statarea_clock_is_calibrated_from_exact_oriented_pairs():
    anchors = [
        {
            "DATE": "20/09/2026",
            "TIME": "13:00",
            "HOME TEAM": "Manchester City",
            "AWAY TEAM": "Sunderland",
        },
        {
            "DATE": "20/09/2026",
            "TIME": "12:00",
            "HOME TEAM": "Kalmar FF",
            "AWAY TEAM": "Häcken",
        },
        {
            "DATE": "20/09/2026",
            "TIME": "10:30",
            "HOME TEAM": "Fiorentina",
            "AWAY TEAM": "Napoli",
        },
    ]
    raw = [
        {
            "DATE": "20/09/2026",
            "TIME": "09:00",
            "SOURCE_DATE": "2026-09-20",
            "SOURCE_TIME": "09:00",
            "HOME TEAM": "Manchester City",
            "AWAY TEAM": "Sunderland",
        },
        {
            "DATE": "20/09/2026",
            "TIME": "08:00",
            "SOURCE_DATE": "2026-09-20",
            "SOURCE_TIME": "08:00",
            "HOME TEAM": "Kalmar FF",
            "AWAY TEAM": "Häcken",
        },
        {
            "DATE": "20/09/2026",
            "TIME": "06:30",
            "SOURCE_DATE": "2026-09-20",
            "SOURCE_TIME": "06:30",
            "HOME TEAM": "Fiorentina",
            "AWAY TEAM": "Napoli",
        },
    ]

    offset, meta = infer_statarea_clock_offset(raw, anchors)

    assert offset == -240
    assert meta["samples"] == 3
    assert meta["dominant_samples"] == 3
    assert meta["dominance"] == 1.0

    normalized = _apply_clock_offset(raw, offset)
    assert normalized[0]["TIME"] == "13:00"
    assert normalized[1]["TIME"] == "12:00"
    assert normalized[2]["TIME"] == "10:30"



def test_statarea_clock_clusters_small_kickoff_rounding_differences():
    anchors = [
        {
            "DATE": "21/09/2026",
            "TIME": "17:30",
            "HOME TEAM": "Aldosivi",
            "AWAY TEAM": "Atletico Tucuman",
        },
        {
            "DATE": "21/09/2026",
            "TIME": "22:00",
            "HOME TEAM": "Barracas Central",
            "AWAY TEAM": "Independiente Rivadavia",
        },
        {
            "DATE": "22/09/2026",
            "TIME": "00:30",
            "HOME TEAM": "Cuiaba",
            "AWAY TEAM": "Nautico",
        },
    ]
    raw = [
        {
            "SOURCE_DATE": "2026-09-21",
            "SOURCE_TIME": "10:30",
            "HOME TEAM": "Aldosivi",
            "AWAY TEAM": "Atletico Tucuman",
        },
        {
            "SOURCE_DATE": "2026-09-21",
            "SOURCE_TIME": "15:00",
            "HOME TEAM": "Barracas Central",
            "AWAY TEAM": "Independiente Rivadavia",
        },
        {
            "SOURCE_DATE": "2026-09-21",
            "SOURCE_TIME": "17:33",
            "HOME TEAM": "Cuiaba",
            "AWAY TEAM": "Nautico",
        },
    ]

    offset, meta = infer_statarea_clock_offset(raw, anchors)

    assert offset == -420
    assert meta["samples"] == 3
    assert meta["dominant_samples"] == 3
    assert meta["dominance"] == 1.0
    assert meta["offset_tolerance_minutes"] == 5
    assert meta["dominant_cluster"] == [-420, -420, -417]
    assert meta["reason"] == "DOMINANT_TOLERANT_CLOCK_OFFSET"

def test_statarea_clock_refuses_ambiguous_offsets():
    anchors = [
        {
            "DATE": "20/09/2026",
            "TIME": "13:00",
            "HOME TEAM": "A",
            "AWAY TEAM": "B",
        },
        {
            "DATE": "20/09/2026",
            "TIME": "13:00",
            "HOME TEAM": "C",
            "AWAY TEAM": "D",
        },
        {
            "DATE": "20/09/2026",
            "TIME": "13:00",
            "HOME TEAM": "E",
            "AWAY TEAM": "F",
        },
        {
            "DATE": "20/09/2026",
            "TIME": "13:00",
            "HOME TEAM": "G",
            "AWAY TEAM": "H",
        },
    ]
    raw = [
        {
            "SOURCE_DATE": "2026-09-20",
            "SOURCE_TIME": "09:00",
            "HOME TEAM": "A",
            "AWAY TEAM": "B",
        },
        {
            "SOURCE_DATE": "2026-09-20",
            "SOURCE_TIME": "09:00",
            "HOME TEAM": "C",
            "AWAY TEAM": "D",
        },
        {
            "SOURCE_DATE": "2026-09-20",
            "SOURCE_TIME": "10:00",
            "HOME TEAM": "E",
            "AWAY TEAM": "F",
        },
        {
            "SOURCE_DATE": "2026-09-20",
            "SOURCE_TIME": "10:00",
            "HOME TEAM": "G",
            "AWAY TEAM": "H",
        },
    ]

    offset, meta = infer_statarea_clock_offset(raw, anchors)

    assert offset is None
    assert meta["reason"] == "AMBIGUOUS_CLOCK_OFFSET"
