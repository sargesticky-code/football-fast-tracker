"""Production entrypoint for the HKJC-gated Forebet feed.

The Forebet date page can display/encode some early-HKT fixtures as the previous
calendar date because of timezone handling. We already chose the page from the
HKJC HKT target date, so force parsed rows to that requested page date rather
than spending a second ScraperAPI request for the previous date.
"""
from __future__ import annotations

import scrape_forebet as feed

# ScraperAPI reported 10 credits for the successful Forebet request. Refuse any
# future request that would cost more instead of silently burning free credits.
feed.MAX_COST = "10"

# parse_forebet_rows() resolves this global at runtime. Treat every row on the
# requested date page as belonging to the requested HKJC target date for the
# purpose of team-pair matching; final kickoff remains the HKJC HKT kickoff.
def _requested_page_date(_value: str, fallback: str) -> str:
    return fallback

feed.normalize_date = _requested_page_date

if __name__ == "__main__":
    raise SystemExit(feed.main())
