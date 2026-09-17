"""Fixture-anchored parser for Forebet match-detail Markdown.

Forebet detail pages contain many navigation/sidebar mentions of "1 X 2" before
the real prediction table. This parser identifies the actual fixture heading,
then accepts only a 1X2 table whose nearby headers contain Probability/Prob. %
and Pred. It is intentionally isolated so detail-page format changes do not
couple to the broader recovery engine.
"""
from __future__ import annotations

import re

_METADATA_PREFIX = re.compile(r"^(?:Title|URL Source|Markdown Content):\s*", re.I)
_METADATA_SUFFIX = re.compile(r"\s+Prediction,\s*Stats,\s*H2H\b.*$", re.I)


def _plain_markdown_line(value: str) -> str:
    value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = value.replace("**", "").replace("__", "")
    value = re.sub(r"^#+\s*", "", value)
    return " ".join(value.split()).strip()


def _team_label(value: str) -> str:
    value = _METADATA_PREFIX.sub("", value or "")
    value = _METADATA_SUFFIX.sub("", value)
    return " ".join(value.split()).strip(" -")


def _probability_triple(line: str) -> tuple[int, int, int] | None:
    numbers = [int(x) for x in re.findall(r"(?<!\d)(\d{1,3})(?!\d)", line)]
    if len(numbers) != 3:
        return None
    # Forebet publishes integer-rounded probabilities. Three independently
    # rounded percentages can legitimately total 99, 100 or 101.
    total = sum(numbers)
    if any(x < 0 or x > 100 for x in numbers) or not 99 <= total <= 101:
        return None
    return numbers[0], numbers[1], numbers[2]


def _fixture_heading(production, lines: list[str], target: dict) -> tuple[str, str, int]:
    target_home = str(target.get("home_en") or "").strip()
    target_away = str(target.get("away_en") or "").strip()
    best: tuple[float, int, str, str, int] | None = None

    for index, line in enumerate(lines):
        match = re.match(r"^(.+?)\s+VS\s+(.+?)$", line, flags=re.I)
        if not match:
            continue
        home = _team_label(match.group(1))
        away = _team_label(match.group(2))
        hs = production.feed.team_score(home, target_home)
        aws = production.feed.team_score(away, target_away)
        avg = (hs + aws) / 2
        if hs < 0.68 or aws < 0.68 or avg < 0.76:
            continue
        # On equal match quality prefer the shorter/cleaner heading over a
        # page-title wrapper such as "... Prediction, Stats, H2H - ...".
        cleanliness = -(len(home) + len(away))
        candidate = (avg, cleanliness, home, away, index)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    if best is not None:
        return best[2], best[3], best[4]
    return target_home, target_away, -1


def _table_section(lines: list[str], fixture_index: int) -> int:
    """Return the real full-time 1X2 table, never a navigation/sidebar label."""
    candidates: list[int] = []
    for index, line in enumerate(lines):
        if not re.fullmatch(r"1\s+X\s+2", line, flags=re.I):
            continue
        before = " ".join(lines[max(0, index - 8):index])
        after = " ".join(lines[index + 1:min(len(lines), index + 9)])
        has_prob = bool(re.search(r"\bProb\.?\s*%|\bProbability\s*%", before, flags=re.I))
        has_pred = bool(re.search(r"\bPred\b", after, flags=re.I))
        if has_prob and has_pred:
            candidates.append(index)

    if not candidates:
        return -1
    if fixture_index >= 0:
        after_fixture = [index for index in candidates if index > fixture_index]
        if after_fixture:
            return min(after_fixture, key=lambda index: index - fixture_index)
    return candidates[0]


def parse_detail_model(production, body: str, target: dict, match_date: str) -> dict[str, str] | None:
    raw_lines = [line.strip() for line in body.splitlines() if line.strip()]
    lines = [_plain_markdown_line(line) for line in raw_lines]
    lines = [line for line in lines if line]
    if not lines:
        return None

    source_home, source_away, fixture_index = _fixture_heading(production, lines, target)
    hs = production.feed.team_score(source_home, target.get("home_en", ""))
    aws = production.feed.team_score(source_away, target.get("away_en", ""))
    if hs < 0.68 or aws < 0.68 or (hs + aws) / 2 < 0.76:
        print(
            f"FOREBET_DETAIL_STAGE_FAIL stage=fixture event={target.get('hkjc_event_id','')} "
            f"home={source_home!r} away={source_away!r}",
            flush=True,
        )
        return None

    section = _table_section(lines, fixture_index)
    if section < 0:
        print(
            f"FOREBET_DETAIL_STAGE_FAIL stage=table_header event={target.get('hkjc_event_id','')} "
            f"fixture_index={fixture_index}",
            flush=True,
        )
        return None

    probs: tuple[int, int, int] | None = None
    prob_index = -1
    for index in range(section + 1, min(len(lines), section + 90)):
        if index > section + 8 and re.search(r"Under/Over", lines[index], flags=re.I):
            break
        candidate = _probability_triple(lines[index])
        if candidate:
            probs = candidate
            prob_index = index
            break
    if probs is None:
        print(
            f"FOREBET_DETAIL_STAGE_FAIL stage=probabilities event={target.get('hkjc_event_id','')} "
            f"section={section}",
            flush=True,
        )
        return None

    prediction = ""
    score = ""
    prediction_index = -1
    for index in range(prob_index + 1, min(len(lines), prob_index + 16)):
        line = lines[index]
        match = re.match(r"^([12Xx])(?:\s+(\d+)\s*-\s*(\d+))?(?:\s.*)?$", line)
        if not match:
            continue
        prediction = match.group(1).upper()
        prediction_index = index
        if match.group(2) is not None and match.group(3) is not None:
            score = f"{match.group(2)} - {match.group(3)}"
        break
    if not prediction:
        print(
            f"FOREBET_DETAIL_STAGE_FAIL stage=prediction event={target.get('hkjc_event_id','')} "
            f"prob_index={prob_index}",
            flush=True,
        )
        return None

    score_index = prediction_index
    if not score:
        for index in range(prediction_index + 1, min(len(lines), prediction_index + 10)):
            match = re.search(r"(?<!\d)(\d+)\s*-\s*(\d+)(?!\d)", lines[index])
            if match:
                score = f"{match.group(1)} - {match.group(2)}"
                score_index = index
                break

    avg_goals = ""
    for index in range(score_index + 1, min(len(lines), score_index + 10)):
        match = re.fullmatch(r"(\d{1,2}\.\d{1,2})", lines[index])
        if match:
            avg_goals = match.group(1)
            break

    print(
        f"FOREBET_DETAIL_PARSED event={target.get('hkjc_event_id','')} "
        f"section={section} probs={probs[0]}/{probs[1]}/{probs[2]} "
        f"pred={prediction} score={score or '-'} avg={avg_goals or '-'}",
        flush=True,
    )
    return {
        "home": source_home,
        "away": source_away,
        "home_prob": str(probs[0]),
        "draw_prob": str(probs[1]),
        "away_prob": str(probs[2]),
        "prediction": prediction,
        "score": score,
        "avg_goals": avg_goals,
        "match_date": match_date,
        "kickoff": str(target.get("kickoff_hkt") or ""),
        "league": str(target.get("league_zh") or ""),
    }


def install(recovery_module) -> None:
    recovery_module._parse_detail_model = parse_detail_model
