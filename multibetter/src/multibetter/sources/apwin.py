from __future__ import annotations

import re
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from multibetter.models import SourcePrediction
from multibetter.sources.base import SourceAdapter


_APWIN_PREDICTION_RE = re.compile(r"^/predictions/.+-prediction-.+/$")
_URL_DATE_RE = re.compile(r"-(\d{2})-(\d{2})-(\d{4})/$")
_H1_RE = re.compile(
    r"^(?P<home>.+?)\s+vs\s+(?P<away>.+?)\s*\|\s*Prediction\s*\|\s*"
    r"(?P<competition>.+?)\s*\|\s*(?P<day>\d{2}/\d{2})\s*$",
    re.IGNORECASE,
)


class APWinAdapter(SourceAdapter):
    """APWin V2 source adapter.

    Discovery is APWin-native: crawl APWin's predictions index and keep only
    prediction URLs whose URL date matches the requested day. No search-engine
    discovery and no fuzzy HKJC matching is used here.

    Parsed APWin records are later matched to Forebet reference teams by the
    Multibetter matcher.
    """

    name = "APWIN"
    base_url = "https://www.apwin.com"

    def __init__(self, *, session: requests.Session | None = None, timeout: int = 20):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-GB,en;q=0.9",
            }
        )

    def predictions_index(self, day: date) -> str:
        return f"{self.base_url}/predictions/"

    @staticmethod
    def is_prediction_url(url: str) -> bool:
        parsed = urlparse(url)
        return (
            parsed.netloc in {"www.apwin.com", "apwin.com"}
            and bool(_APWIN_PREDICTION_RE.match(parsed.path))
        )

    @staticmethod
    def date_from_prediction_url(url: str) -> date | None:
        match = _URL_DATE_RE.search(urlparse(url).path)
        if not match:
            return None
        dd, mm, yyyy = map(int, match.groups())
        return date(yyyy, mm, dd)

    def _get_html(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def parse_index_html(self, html: str, day: date) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        found: list[str] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            url = urljoin(self.base_url, anchor["href"])
            if not self.is_prediction_url(url):
                continue
            if self.date_from_prediction_url(url) != day:
                continue
            if url in seen:
                continue
            seen.add(url)
            found.append(url)

        return found

    def discover(self, day: date) -> list[str]:
        html = self._get_html(self.predictions_index(day))
        return self.parse_index_html(html, day)

    @staticmethod
    def _first_match(pattern: str, text: str, *, flags: int = 0) -> str | None:
        match = re.search(pattern, text, flags)
        return match.group(1).strip() if match else None

    def parse_detail_html(self, html: str, url: str) -> SourcePrediction:
        if not self.is_prediction_url(url):
            raise ValueError(f"Not an APWin prediction URL: {url}")

        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        if h1 is None:
            raise ValueError("APWin detail page has no H1")

        heading = " ".join(h1.stripped_strings)
        match = _H1_RE.match(heading)
        if not match:
            raise ValueError(f"Unrecognised APWin prediction heading: {heading}")

        page_text = soup.get_text("\n", strip=True)
        fixture_date = self.date_from_prediction_url(url)

        main_prediction = self._first_match(
            r"APWin Prediction\s*\n\s*([^\n]+)",
            page_text,
            flags=re.IGNORECASE,
        )
        expert_recommendation = self._first_match(
            r"Our prediction is:\s*([^\n]+)",
            page_text,
            flags=re.IGNORECASE,
        )
        prediction_odds = self._first_match(
            r"Odds of Prediction:\s*([0-9]+(?:\.[0-9]+)?)",
            page_text,
            flags=re.IGNORECASE,
        )
        source_kickoff_text = self._first_match(
            r"\bat\s+(\d{1,2}:\d{2})\s*\(UK Time\)",
            page_text,
            flags=re.IGNORECASE,
        )

        recommendations: dict[str, str] = {}
        if main_prediction:
            recommendations["apwin_prediction"] = main_prediction
        if expert_recommendation:
            recommendations["expert_recommendation"] = expert_recommendation

        odds: dict[str, float] = {}
        if prediction_odds is not None:
            odds["prediction_odds"] = float(prediction_odds)

        return SourcePrediction(
            source=self.name,
            kickoff=None,
            fixture_date=fixture_date,
            competition=match.group("competition").strip(),
            home=match.group("home").strip(),
            away=match.group("away").strip(),
            source_url=url,
            fetched_at=datetime.now(timezone.utc),
            recommendations=recommendations,
            odds=odds,
            market_label=main_prediction,
            source_kickoff_text=source_kickoff_text,
        )

    def fetch_prediction(self, url: str) -> SourcePrediction:
        html = self._get_html(url)
        return self.parse_detail_html(html, url)
