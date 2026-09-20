"""Durable Forebet <-> HKJC team-name matching policy.

This module sits above the legacy parser and handles recurring source-name
patterns without growing a one-off hard-coded alias list for every fixture.
Verified provider-specific exceptions live in data/team_alias_manual.csv while
the rolling learned registry remains the final persistent evidence store.
"""
from __future__ import annotations

import csv
import re
from difflib import SequenceMatcher

import scrape_forebet as feed

_LEGACY_NORMALIZE = feed.normalize_team
MANUAL_ALIAS_FILE = feed.ROOT / "data" / "team_alias_manual.csv"

EXTRA_STOPWORDS = {"al"}

SHORT_TOKEN_DENY = {
    "real", "city", "town", "utd", "club", "team", "sport", "united",
    "fc", "sc", "ac", "cf", "afc", "fk", "ca", "cd", "if", "bk", "sk",
}

_COUNTRY_TAG = re.compile(r"\(\s*[A-Z]{2,4}\s*\)")

_SPECIAL_LATIN = str.maketrans({
    "æ": "ae", "Æ": "AE",
    "ø": "o",  "Ø": "O",
    "å": "a",  "Å": "A",
    "ð": "d",  "Ð": "D",
    "þ": "th", "Þ": "Th",
    "ł": "l",  "Ł": "L",
    "đ": "d",  "Đ": "D",
    "ß": "ss",
})


def _load_manual_aliases() -> int:
    if not MANUAL_ALIAS_FILE.exists():
        return 0
    loaded = 0
    with MANUAL_ALIAS_FILE.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            alias = str(row.get("forebet_alias") or "").strip()
            canonical = str(row.get("canonical_hkjc_name") or "").strip()
            if not alias or not canonical:
                continue
            alias_key = _LEGACY_NORMALIZE(alias)
            canonical_value = _LEGACY_NORMALIZE(canonical)
            if alias_key and canonical_value:
                feed.ALIASES[alias_key] = canonical_value
                loaded += 1
    return loaded


def normalize_team(value: str) -> str:
    """Normalize stable provider-wide source naming differences."""
    raw = str(value or "")
    raw = _COUNTRY_TAG.sub(" ", raw)
    raw = raw.translate(_SPECIAL_LATIN)
    base = _LEGACY_NORMALIZE(raw)
    tokens = [t for t in base.split() if t not in EXTRA_STOPWORDS]

    normalized: list[str] = []
    for index, token in enumerate(tokens):
        if token in {"st", "saint"}:
            token = "saint"
        elif index == len(tokens) - 1 and token in {"w", "women", "woman"}:
            token = "women"
        normalized.append(token)
    return " ".join(normalized).strip()


def team_score(a: str, b: str) -> float:
    """Return a conservative name similarity score with acronym support."""
    a_n = normalize_team(a)
    b_n = normalize_team(b)
    if not a_n or not b_n:
        return 0.0
    if a_n == b_n:
        return 1.0
    if min(len(a_n), len(b_n)) >= 5 and (a_n in b_n or b_n in a_n):
        return 0.96

    seq = SequenceMatcher(None, a_n, b_n).ratio()
    a_tokens = set(a_n.split())
    b_tokens = set(b_n.split())
    if a_tokens and b_tokens:
        inter = len(a_tokens & b_tokens)
        token_score = 2 * inter / (len(a_tokens) + len(b_tokens))
    else:
        token_score = 0.0
    score = max(seq, token_score)

    shared_short = {
        t for t in (a_tokens & b_tokens)
        if 3 <= len(t) <= 4 and t not in SHORT_TOKEN_DENY and t.isalpha()
    }
    if shared_short:
        score = max(score, 0.92)
    return score


def install() -> None:
    """Install permanent aliases and matching policy before production imports."""
    loaded = _load_manual_aliases()
    feed.normalize_team = normalize_team
    feed.team_score = team_score
    print(f"FOREBET_MANUAL_ALIAS_SEEDS rows={loaded}", flush=True)
