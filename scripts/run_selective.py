"""Production entrypoint for the HKJC-gated Forebet feed.

Only keep fixtures that are currently offered by HKJC HAD *and* have a usable
Forebet 1X2 probability triplet. This is deliberately selective: unrelated
Forebet matches are discarded and model-empty overlaps are also discarded.
"""
from __future__ import annotations

import scrape_forebet as feed

# The successful request cost 10 credits. Refuse any request that would cost
# more instead of silently burning the free ScraperAPI allowance.
feed.MAX_COST = "10"

# Forebet can encode early-HKT fixtures with the previous calendar date. The
# page itself was chosen from the HKJC HKT target date, so use that page date
# for pair matching instead of spending a second ScraperAPI request.
def _requested_page_date(_value: str, fallback: str) -> str:
    return fallback

feed.normalize_date = _requested_page_date

# A match is not useful to Fast Tracker without all three 1X2 model
# probabilities. Filter it before it can be written to the production CSV.
_original_attach = feed.attach_hkjc_target


def _attach_only_usable(row, targets):
    probs = (row.get("prob_home"), row.get("prob_draw"), row.get("prob_away"))
    if not all(isinstance(v, (int, float)) for v in probs):
        return None
    return _original_attach(row, targets)


feed.attach_hkjc_target = _attach_only_usable

if __name__ == "__main__":
    raise SystemExit(feed.main())
