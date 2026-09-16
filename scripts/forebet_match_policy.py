"""Durable Forebet <-> HKJC team-name matching policy.

This module sits above the legacy parser and handles recurring source-name
patterns without growing a one-off hard-coded alias list for every fixture.
The persistent alias registry remains the final authority once a mapping has
been learned.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

import scrape_forebet as feed

_LEGACY_NORMALIZE = feed.normalize_team

# Article/prefix noise that does not identify the club.  Keep this list small:
# it is applied only after the legacy normalizer and alias registry.
EXTRA_STOPWORDS = {"al"}

# A shared 3-4 letter token is useful for distinctive club acronyms (AIK, PSV,
# AEK, etc.), but these generic tokens must never be used as the sole anchor.
SHORT_TOKEN_DENY = {
    "real", "city", "town", "utd", "club", "team", "sport", "united",
    "fc", "sc", "ac", "cf", "afc", "fk", "ca", "cd", "if", "bk", "sk",
}

_COUNTRY_TAG = re.compile(r"\(\s*[A-Z]{2,4}\s*\)")


def normalize_team(value: str) -> str:
    """Normalize source noise while preserving the registry's canonical logic.

    Forebet commonly appends country disambiguators such as ``(URU)`` or
    ``(OMA)``.  HKJC normally does not.  Removing only uppercase country tags
    before the legacy normalization is safe and repeatable.
    """
    raw = str(value or "")
    raw = _COUNTRY_TAG.sub(" ", raw)
    base = _LEGACY_NORMALIZE(raw)
    tokens = [t for t in base.split() if t not in EXTRA_STOPWORDS]
    return " ".join(tokens).strip()


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

    # Distinctive acronym anchor.  This solves stable source variants such as
    # AIK Fotboll vs AIK Solna without treating generic words like Real/City
    # as sufficient evidence.
    shared_short = {
        t for t in (a_tokens & b_tokens)
        if 3 <= len(t) <= 4 and t not in SHORT_TOKEN_DENY and t.isalpha()
    }
    if shared_short:
        score = max(score, 0.92)
    return score


def install() -> None:
    """Install the policy into the legacy parser before production imports it."""
    feed.normalize_team = normalize_team
    feed.team_score = team_score
