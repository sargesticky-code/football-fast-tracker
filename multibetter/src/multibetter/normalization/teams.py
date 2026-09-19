from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

from multibetter.models import TeamClass


_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("&", " and ")
    value = _PUNCT.sub(" ", value)
    return _SPACE.sub(" ", value).strip()


def classify_team(name: str) -> TeamClass:
    n = f" {normalize_text(name)} "

    if re.search(r"\b(women|woman|ladies|femenin[oa]|femeni|wfc)\b", n):
        return TeamClass.WOMEN
    if re.search(r"\b(u1[6789]|u2[013]|under ?(?:17|18|19|20|21|23)|youth|academy)\b", n):
        return TeamClass.YOUTH
    if re.search(r"\b(reserve|reserves|res)\b", n):
        return TeamClass.RESERVE
    if re.search(r"\b(ii|b team|team b|b)\b", n):
        return TeamClass.B_TEAM
    return TeamClass.SENIOR


def canonicalize_team(name: str, aliases: Mapping[str, str] | None = None) -> tuple[str, bool]:
    n = normalize_text(name)
    if not aliases:
        return n, False

    normalized_aliases = {normalize_text(k): normalize_text(v) for k, v in aliases.items()}
    if n in normalized_aliases:
        return normalized_aliases[n], True
    return n, False
