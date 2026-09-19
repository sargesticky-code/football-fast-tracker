from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class IntakeStatus(str, Enum):
    OK = "OK"
    STALE = "STALE"
    FETCH_ERROR = "FETCH_ERROR"
    PARSER_ERROR = "PARSER_ERROR"
    BLOCKED = "BLOCKED"
    NO_MATCH = "NO_MATCH"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"


@dataclass(frozen=True)
class SourceHealth:
    source: str
    status: IntakeStatus
    fetched_at: datetime | None
    rows: int = 0
    matched: int = 0
    rejected: int = 0
    parser_errors: int = 0
    note: str = ""

    @property
    def coverage(self) -> float:
        total = self.matched + self.rejected
        return 0.0 if total == 0 else self.matched / total
