from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse

from multibetter.sources.base import SourceAdapter


_APWIN_PREDICTION_RE = re.compile(r"^/predictions/.+-prediction-.+/$")


class APWinAdapter(SourceAdapter):
    """APWin V2 adapter boundary.

    V1 intentionally does not perform fuzzy Google/web discovery.
    Discovery must start from APWin-owned index/listing pages, then strict matching
    decides whether a candidate belongs to an HKJC fixture.
    """

    name = "APWIN"
    base_url = "https://www.apwin.com"

    def predictions_index(self, day: date) -> str:
        # APWin's general predictions index is the discovery starting point.
        # Date filtering is handled by the page parser / candidate metadata.
        return f"{self.base_url}/predictions/"

    @staticmethod
    def is_prediction_url(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc in {"www.apwin.com", "apwin.com"} and bool(_APWIN_PREDICTION_RE.match(parsed.path))

    def discover(self, day: date):
        raise NotImplementedError("APWin index crawler is the next Multibetter milestone")

    def fetch_prediction(self, url: str):
        raise NotImplementedError("APWin detail parser is the next Multibetter milestone")
