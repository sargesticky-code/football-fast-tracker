"""Ephemeral competition corroboration from this SAME Forebet capture.

Unknown source league codes can tentatively match one-team events only when
three *already independently published* strict two-team fixtures corroborate
one and only one Flashscore league, with five distinct teams. No DB reads,
new scraping, permanent aliases or promotion to verified forecast evidence.
"""
from __future__ import annotations
from collections import defaultdict
import re

from forebet_canonical_source_probe import exact_name
from capture_forebet_canonical_light import LEAGUE_PREFIX


MIN_STRICT_FIXTURES = 3
MIN_DISTINCT_TEAMS = 5


def verified_competition_cohorts(source_rows, targets, strict_rows):
    by_id = {t["match_id"]: t for t in targets}
    by_url = defaultdict(list)
    for row in source_rows:
        by_url[str(row.get("forebet_detail_url") or "")].append(row)
    evidence = defaultdict(list)
    for observation in strict_rows:
        code = str(observation.get("source_league") or "")
        if code in LEAGUE_PREFIX or not re.fullmatch(r"[A-Za-z0-9]{2,10}", code):
            continue
        if observation.get("league_verification") not in (
            "EXACT_NAMES_AND_UTC_TIME_ONLY",
            "TWO_SHARED_PROVIDER_TEAM_KEYS_AND_UNIQUE_UTC_FIXTURE",
        ):
            continue
        target = by_id.get(observation.get("match_id"))
        rows = by_url.get(str(observation.get("source_event_url") or ""), [])
        if not target or len(rows) != 1:
            continue
        source = rows[0]
        if str(source.get("league_short") or "") != code:
            continue
        # Strongest independent evidence: exact names on both sides,
        # in home/away order. A bridged ID alone is not sufficient to teach
        # an unknown competition even though it can verify a single event.
        if (exact_name(source.get("home_team")) != exact_name(target["home"])
            or exact_name(source.get("away_team")) != exact_name(target["away"])):
            continue
        if not isinstance(target.get("league"), str) or not target["league"]:
            continue
        evidence[code].append((target["match_id"], target["league"],
                               target["home"], target["away"]))
    out = {}
    for code, observations in evidence.items():
        mids = {x[0] for x in observations}
        league_names = {x[1] for x in observations}
        teams = {name for x in observations for name in x[2:4]}
        # A code seen in two different Flashscore leagues is contradictory:
        # never select the majority league, never persist a guessed alias.
        if (len(mids) >= MIN_STRICT_FIXTURES and len(mids) == len(observations)
            and len(league_names) == 1
            and len(teams) >= MIN_DISTINCT_TEAMS):
            out[code] = next(iter(league_names))
    return out
