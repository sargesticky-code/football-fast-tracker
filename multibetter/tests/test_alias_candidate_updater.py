from multibetter.scripts.update_alias_candidates import update_candidates


def test_candidate_evidence_persists_across_runs():
    observations1 = [
        {
            "github_forebet_alias": "Liverpool (URU)",
            "our_forebet_candidate": "Liverpool Montevideo",
            "observed_at": "2026-09-20T08:00:00",
            "similarity": "90",
            "opponent": "Ind Medellin",
            "event_id": "A",
        }
    ]
    first = update_candidates([], observations1)
    assert first[0]["observation_count"] == "1"
    assert first[0]["status"] == "CANDIDATE"

    observations2 = [
        {
            "github_forebet_alias": "Liverpool (URU)",
            "our_forebet_candidate": "Liverpool Montevideo",
            "observed_at": "2026-09-21T08:00:00",
            "similarity": "92",
            "opponent": "Nacional",
            "event_id": "B",
        },
        {
            "github_forebet_alias": "Liverpool (URU)",
            "our_forebet_candidate": "Liverpool Montevideo",
            "observed_at": "2026-09-22T08:00:00",
            "similarity": "91",
            "opponent": "Penarol",
            "event_id": "C",
        },
    ]
    second = update_candidates(first, observations2)
    assert second[0]["observation_count"] == "3"
    assert second[0]["status"] == "REVIEW_READY"
    assert second[0]["distinct_opponents"] == "Ind Medellin|Nacional|Penarol"
