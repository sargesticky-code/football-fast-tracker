"""Strictly bounded, *provisional* one-team Forebet matching.

This NEVER writes verified predictions. It proposes tentative associations
for an independent, revocable persistence contract. One verified side, verified
competition, ordered venue, unique exact kickoff and one-to-one source↔target
are necessary. Remaining side is NOT guessed or saved as a verified alias.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher
from functools import lru_cache
from datetime import datetime, timedelta, timezone
import re

from forebet_canonical_source_probe import exact_name, model_fields
from capture_forebet_canonical_light import displayed_wall_clock, league_ok, LEAGUE_PREFIX
from forebet_verified_aliases import verified_source_name, verified_shared_source_name, norm
from forebet_league_cohort import verified_competition_cohorts

MAX_PROVISIONALS = 180
FUZZY_NAME_FLOOR = 0.30
FUZZY_STRONG_SIDE = 0.70


@lru_cache(maxsize=16000)
def _name_ratio(left, right):
    """Case/accent/punctuation normalised *candidate* similarity, not P(match)."""
    a, b = norm(left), norm(right)
    if min(len(a), len(b)) < 5 or a == b:
        return 0.0 if not a or not b else (1.0 if a == b else 0.0)
    return round(SequenceMatcher(None, a, b, autojunk=False).ratio(), 5)



def tentative_rows(source_rows, targets, verified_rows, now):
    accepted = {x["match_id"] for x in verified_rows}
    corroborated_leagues = verified_competition_cohorts(source_rows, targets, verified_rows)
    proposed = defaultdict(list)
    fuzzy_proposed = defaultdict(list)
    candidates_per_source = defaultdict(set)
    fuzzy_sources = defaultdict(set)
    counters = Counter()
    for row in source_rows:
        fields, wall = model_fields(row), displayed_wall_clock(row)
        if not fields or wall is None:
            continue
        src_time = wall.replace(tzinfo=timezone.utc)
        if not now < src_time <= now + timedelta(hours=48):
            continue
        source_url = str(row.get("forebet_detail_url") or "")
        if not re.fullmatch(
            r"https://www[.]forebet[.]com/en/football/matches/[^?#]{2,240}-[0-9]{5,12}",
            source_url,
        ):
            counters["invalid_source_identity"] += 1
            continue
        code = str(row.get("league_short") or "")
        if code not in LEAGUE_PREFIX and code not in corroborated_leagues:
            counters["unverified_source_league"] += 1
            continue
        for t in targets:
            mid = t["match_id"]
            if mid in accepted or not now < t["kickoff"] <= now + timedelta(hours=48):
                continue
            if abs((t["kickoff"] - src_time).total_seconds()) > 60:
                continue
            # We need known-source-league agreement, not merely overlapping
            # team names in games with synchronized kickoff times.
            # Unknown competition is admitted ONLY when independently
            # corroborated by >=3 strict, exact, cross-provider fixtures in
            # this same complete source capture. Still provisional only.
            league_proof = ("VERIFIED_STATIC_LEAGUE_CODE" if code in LEAGUE_PREFIX
                else "SAME_CAPTURE_3_STRICT_TWO_TEAM_FIXTURES")
            league_supported = (league_ok(code,t.get("league")) if code in LEAGUE_PREFIX
                else corroborated_leagues.get(code) == t.get("league"))
            if not league_supported:
                continue
            h = verified_source_name(row.get("home_team"), t["home"])
            a = verified_source_name(row.get("away_team"), t["away"])
            if h and a:  # strict two-side publisher owns this identity
                continue
            # Existing one-side verified identity always wins. Fuzzy names
            # NEVER replace or certify a previously verified alias.
            if h or a:
                which = "HOME" if h else "AWAY"
                fuzzy = False
            else:
                # A provider-verified mismatching key is explicit counter-
                # evidence and must not be overruled by spell similarity.
                if (verified_shared_source_name(row.get("home_team"), t["home"]) is False
                    or verified_shared_source_name(row.get("away_team"), t["away"]) is False):
                    counters["known_verified_identity_conflict"] += 1
                    continue
                hs = _name_ratio(str(row.get("home_team") or ""),str(t["home"]))
                aws = _name_ratio(str(row.get("away_team") or ""),str(t["away"]))
                if min(hs,aws) < FUZZY_NAME_FLOOR or max(hs,aws) < FUZZY_STRONG_SIDE:
                    continue
                which = "SIMILARITY"
                fuzzy = True
            candidate = {
                "match_id":mid,
                "source_url":source_url,
                "source_home":row["home_team"],
                "source_away":row["away_team"],
                "canonical_home":t["home"],
                "canonical_away":t["away"],
                "kickoff":t["kickoff"].isoformat(),
                "source_clock_utc":src_time.isoformat(),
                "source_league":code,
                "canonical_league":t["league"],
                "one_verified_side":which,
                "home":fields["home"],"draw":fields["draw"],"away":fields["away"],
                "pick":fields["pick"],"score":fields["score"],
                "avg_goals":fields["avg_goals"],
                "matched_identity":("BOTH_NAME_SIMILARITY_030_STRONG_SIDE_070_LEAGUE_EXACT_TIME_UNIQUE"
                    if fuzzy else "ONE_SIDE_WITH_CONFIRMED_COMPETITION_AND_UNIQUE_KICKOFF"),
                "league_verification":league_proof,
                **({"home_similarity":hs,"away_similarity":aws,
                    "similarity_method":"NFKD_CASEFOLD_SEQUENCE_RATIO_V1"} if fuzzy else {}),
            }
            if fuzzy:
                fuzzy_proposed[mid].append(candidate)
                fuzzy_sources[source_url].add(mid)
            else:
                proposed[mid].append(candidate)
                candidates_per_source[source_url].add(mid)
    # Fuzzy-only candidates may not displace a corroborated verified side.
    for mid, choices in fuzzy_proposed.items():
        if mid in proposed:
            counters["fuzzy_rejected_by_verified_side"] += 1
            continue
        unique = {(c["source_url"],c["source_home"],c["source_away"]) for c in choices}
        if len(choices) != 1 or len(unique) != 1:
            counters["fuzzy_multiple_source_candidates"] += 1
            continue
        src = choices[0]["source_url"]
        if (len(fuzzy_sources[src]) != 1 or src in candidates_per_source):
            counters["fuzzy_competing_canonical"] += 1
            continue
        proposed[mid].append(choices[0])
        candidates_per_source[src].add(mid)
    output = []
    for mid, choices in proposed.items():
        distinct = {(x["source_url"],x["source_home"],x["source_away"])
                    for x in choices}
        if len(choices) != 1 or len(distinct) != 1:
            counters["multiple_source_candidates"] += 1
            continue
        c = choices[0]
        if len(candidates_per_source[c["source_url"]]) != 1:
            counters["source_matches_multiple_fixtures"] += 1
            continue
        output.append(c)
    if len(output) > MAX_PROVISIONALS:
        # Never silently truncate a complete source day: omitted candidates
        # would be treated as disappeared, causing incorrect disconnections.
        raise ValueError("PROVISIONAL_CAPACITY_EXCEEDED")
    # An event will never exist twice in the submitted batch.
    if len({x["match_id"] for x in output}) != len(output):
        raise ValueError("DUPLICATE_PROVISIONAL_FIXTURE")
    if len({x["source_url"] for x in output}) != len(output):
        raise ValueError("DUPLICATE_PROVISIONAL_SOURCE")
    counters["crosschecked_league_codes"] = len(corroborated_leagues)
    counters["cohort_based_provisionals"] = sum(
        x["league_verification"]=="SAME_CAPTURE_3_STRICT_TWO_TEAM_FIXTURES"
        for x in output)
    counters["fuzzy_name_floor"] = FUZZY_NAME_FLOOR
    counters["fuzzy_strong_side"] = FUZZY_STRONG_SIDE
    counters["fuzzy_both_name_provisionals"] = sum(
        x["one_verified_side"] == "SIMILARITY" for x in output)
    counters["safe_one_side_provisionals"] = sum(
        x["one_verified_side"] in ("HOME","AWAY") for x in output)
    return sorted(output,key=lambda x:x["match_id"]),dict(counters)
