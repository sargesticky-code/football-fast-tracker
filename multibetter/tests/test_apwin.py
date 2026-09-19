from datetime import date

from multibetter.sources.apwin import APWinAdapter


INDEX_HTML = """
<html><body>
<a href="/predictions/flamengo-vs-bragantino-prediction-serie-a-20-09-2026/">A</a>
<a href="/predictions/flamengo-vs-bragantino-prediction-serie-a-20-09-2026/">duplicate</a>
<a href="/predictions/mirassol-vs-botafogo-prediction-serie-a-19-09-2026/">other day</a>
<a href="/teams/flamengo/">not prediction</a>
</body></html>
"""

DETAIL_HTML = """
<html><body>
<h1>Flamengo vs Bragantino | Prediction | Brazil Serie A | 20/09</h1>
<p>Flamengo and Bragantino face each other on Sunday, 20/09/2026, at 22:30 (UK Time).</p>
<section>
  <h2>APWin Prediction</h2>
  <div>Flamengo Win</div>
  <p>Our prediction is: Both teams to score</p>
</section>
<div>Odds of Prediction: 1.34</div>
</body></html>
"""

URL = "https://www.apwin.com/predictions/flamengo-vs-bragantino-prediction-serie-a-20-09-2026/"


def test_index_census_filters_exact_day_and_deduplicates():
    adapter = APWinAdapter()
    urls = adapter.parse_index_html(INDEX_HTML, date(2026, 9, 20))
    assert urls == [URL]


def test_detail_parser_captures_fixture_and_separate_recommendations():
    adapter = APWinAdapter()
    prediction = adapter.parse_detail_html(DETAIL_HTML, URL)

    assert prediction.fixture_date == date(2026, 9, 20)
    assert prediction.home == "Flamengo"
    assert prediction.away == "Bragantino"
    assert prediction.competition == "Brazil Serie A"
    assert prediction.recommendations["apwin_prediction"] == "Flamengo Win"
    assert prediction.recommendations["expert_recommendation"] == "Both teams to score"
    assert prediction.odds["prediction_odds"] == 1.34
    assert prediction.source_kickoff_text == "22:30"


def test_rejects_non_prediction_urls():
    adapter = APWinAdapter()
    assert not adapter.is_prediction_url("https://www.apwin.com/teams/flamengo/")
