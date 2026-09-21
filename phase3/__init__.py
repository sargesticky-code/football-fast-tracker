"""Phase 3 live-intelligence package.

This package is intentionally isolated from Phase 1 pre-match/value logic and
Phase 2 human-factor logic.
"""

from .hkjc_authority import (
    AuthoritySnapshot,
    evaluate_authority,
)

__all__ = ["AuthoritySnapshot", "evaluate_authority"]
