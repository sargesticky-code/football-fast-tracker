"""Read-only, target-first Forebet↔Flashscore source intersection report.

Source scope is *only* successfully rendered Forebet date pages. Classification
is evidence about this capture, NEVER proof that Forebet lacks a forecast
elsewhere. This module makes zero DB, browser, network or persistence calls.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from forebet_canonical_source_probe import model_fields, exact_name
from forebet_verified_aliases import verified_source_name
from capture_forebet_canonical_light import displayed_wall_clock, league_ok, LEAGUE_PREFIX

COVERAGE_HOURS = 48
CLOCK_TOLERANCE_SECONDS = 60
SOURCE_TOLERANCE_HOURS = 48


def _source_summary(source_rows):
    result = []
    invalid = Counter()
    for row in source_rows:
        clock = displayed_wall_clock(row)
        fields = model_fields(row)
        if clock is None:
            invalid["unusable_source_clock"] += 1
        if not fields:
            invalid["missing_or_invalid_model_fields"] += 1
        if clock is not None:
            result.append((row, clock.replace(tzinfo=timezone.utc), bool(fields)))
    return result, dict(invalid)


def classify_target(target, observations, published):
    """One mutually exclusive outcome per verified canonical fixture."""
    if target["match_id"] in published:
        return "VERIFIED_PUBLISHED", None
    canonical = target["kickoff"].astimezone(timezone.utc)
    h, a = target["home"], target["away"]
    both, broken, one_at_time, any_at_time = [], False, False, False
    near = None
    for row, clock, fields_ok in observations:
        delta = abs((clock - canonical).total_seconds())
        within = delta <= CLOCK_TOLERANCE_SECONDS
        if within:
            any_at_time = True
        left = verified_source_name(row.get("home_team"), h)
        right = verified_source_name(row.get("away_team"), a)
        if left and right:
            if not fields_ok:
                broken = True
            else:
                both.append((row, delta))
        elif within and (left or right):
            one_at_time = True
            if near is None:
                near = row
    if any(seconds <= CLOCK_TOLERANCE_SECONDS for _, seconds in both):
        pair = [(r,s) for r,s in both if s <= CLOCK_TOLERANCE_SECONDS]
        if len(pair) > 1:
            return "MULTIPLE_SOURCE_PAIRS_AT_KICKOFF", pair[0][0]
        row = pair[0][0]
        code = str(row.get("league_short") or "")
        if code in LEAGUE_PREFIX and not league_ok(code,target.get("league")):
            return "KNOWN_LEAGUE_CONFLICT", row
        return "PAIR_AND_TIME_UNPUBLISHED", row
    if both:
        closest = min(both, key=lambda x: x[1])
        return "VERIFIED_PAIR_DIFFERENT_KICKOFF", closest[0]
    if broken:
        return "PAIR_WITH_INVALID_SOURCE_MODEL_OR_CLOCK", None
    if one_at_time:
        return "ONE_VERIFIED_TEAM_AT_SAME_KICKOFF", near
    if any_at_time:
        return "OTHER_SOURCE_MATCHES_AT_SAME_KICKOFF", None
    return "NO_SOURCE_OBSERVATION_AT_KICKOFF", None


def source_intersection_audit(source_rows, targets, published_rows, now, sample_limit=4):
    """Truthful denominator is verified FS targets in the next 48h.

    Never divide by the source-page total or confuse matching with scraping.
    Samples contain only public match names, league and clock; no source HTML.
    """
    targets = [t for t in targets if now < t["kickoff"] <= now + timedelta(hours=COVERAGE_HOURS)]
    observations, invalid = _source_summary(source_rows)
    published = {r["match_id"] for r in published_rows}
    classes = Counter()
    by_league = defaultdict(Counter)
    samples = defaultdict(list)
    for t in targets:
        code, evidence = classify_target(t, observations, published)
        classes[code] += 1
        by_league[t.get("league") or "(unknown)"][code] += 1
        if code != "VERIFIED_PUBLISHED" and len(samples[code]) < sample_limit:
            item = {"fixture":t["match_id"],"league":t.get("league"),
                    "home":t["home"],"away":t["away"],
                    "kickoff_utc":t["kickoff"].astimezone(timezone.utc).isoformat()}
            if evidence:
                item["source_home"] = evidence.get("home_team")
                item["source_away"] = evidence.get("away_team")
                item["source_league"] = evidence.get("league_short")
                item["source_clock"] = evidence.get("kickoff_text")
            samples[code].append(item)
    denominator = len(targets)
    total = sum(classes.values())
    assert total == denominator, "TARGET_FUNNEL_ACCOUNTING_BROKEN"
    listed = sorted(by_league.items(),key=lambda it:(-sum(it[1].values()),it[0]))
    return {
        "metric": "FOREBET_VS_VERIFIED_FLASHSCORE_48H_SOURCE_INTERSECTION",
        "scope_note":"Rows not found in these date pages are unobserved, not proven unavailable on Forebet.",
        "fixture_denominator":denominator,
        "verified_published":classes["VERIFIED_PUBLISHED"],
        "source_rows_input":len(source_rows),
        "source_rows_with_readable_clock":len(observations),
        "source_invalid":invalid,
        "unmatched_by_reason":{k:v for k,v in sorted(classes.items()) if k!="VERIFIED_PUBLISHED"},
        "league_breakdown":[{"league":name,"fixtures":sum(counter.values()),
                              "published":counter["VERIFIED_PUBLISHED"],
                              "unmatched_by_reason":{k:v for k,v in sorted(counter.items())
                                                      if k!="VERIFIED_PUBLISHED"}}
                             for name,counter in listed[:25]],
        "bounded_samples":dict(sorted(samples.items())),
    }
