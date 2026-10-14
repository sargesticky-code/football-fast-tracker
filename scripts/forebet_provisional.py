"""Strictly bounded, *provisional* one-team Forebet matching.

This NEVER writes verified predictions. It proposes tentative associations
for an independent, revocable persistence contract. One verified side, verified
competition, ordered venue, unique exact kickoff and one-to-one source↔target
are necessary. Remaining side is NOT guessed or saved as a verified alias.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import re

from forebet_canonical_source_probe import exact_name, model_fields
from capture_forebet_canonical_light import displayed_wall_clock, league_ok, LEAGUE_PREFIX
from forebet_verified_aliases import verified_source_name

MAX_PROVISIONALS = 180


def tentative_rows(source_rows, targets, verified_rows, now):
    accepted = {x["match_id"] for x in verified_rows}
    proposed = defaultdict(list)
    candidates_per_source = defaultdict(set)
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
        if code not in LEAGUE_PREFIX:
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
            if not league_ok(code, t.get("league")):
                continue
            h = verified_source_name(row.get("home_team"), t["home"])
            a = verified_source_name(row.get("away_team"), t["away"])
            if h == a:  # zero sides or both: two-sided belongs to strict flow
                continue
            # No guessing by similarity. Never reverse home and away.
            which = "HOME" if h else "AWAY"
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
                "matched_identity":"ONE_SIDE_WITH_CONFIRMED_COMPETITION_AND_UNIQUE_KICKOFF",
            }
            proposed[mid].append(candidate)
            candidates_per_source[source_url].add(mid)
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
        raise ValueError("PROVISIONAL_CAPACITY_EXCEEDED")
    # An event will never exist twice in the submitted batch.
    if len({x["match_id"] for x in output}) != len(output):
        raise ValueError("DUPLICATE_PROVISIONAL_FIXTURE")
    if len({x["source_url"] for x in output}) != len(output):
        raise ValueError("DUPLICATE_PROVISIONAL_SOURCE")
    counters["safe_one_side_provisionals"] = len(output)
    return sorted(output,key=lambda x:x["match_id"]),dict(counters)
