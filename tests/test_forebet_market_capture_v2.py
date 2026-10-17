import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from forebet_market_capture_v2 import parse_ou25,parse_corners95,enrich_verified_rows

DATE="2026-10-18"
URL="https://www.forebet.com/en/football/matches/home-away-2495602"
def html_row(market="ou25",under=43,over=57,pick="Over",score="2 - 1",avg="2.75",
             home="Sample Home",away="Sample Away",url=URL,league="EPL",time="10/18/2026 03:00 PM"):
    return f"""<div class="rcnt">
     <span class="homeTeam"><span itemprop="name">{home}</span></span>
     <span class="awayTeam"><span itemprop="name">{away}</span></span>
     <span class="shortTag">{league}</span>
     <time datetime="{DATE}"></time><span class="date_bah">{time}</span>
     <div class="fprc"><span>{under}</span><span>{over}</span></div>
     <span class="forepr"><span>{pick}</span></span>
     <div class="ex_sc tabonly">{score}</div><div class="avg_sc tabonly">{avg}</div>
     <a href="{url}">Details</a></div>"""
def base():
    return {"match_id":"FS:abcde123","source_event_url":URL,
        "source_home":"Sample Home","source_away":"Sample Away",
        "source_league":"EPL","source_event_time":"2026-10-18T15:00:00+00:00",
        "home":35.0,"draw":30.0,"away":35.0,"avg_goals":2.78,
        "score":"2 - 1"}
class MarketCaptureTests(unittest.TestCase):
    def test_both_markets_join_exact_source_identity(self):
        goal=parse_ou25(html_row(),"2026-10-18")
        corners=parse_corners95(html_row("corners95",47,53,"Over","5 - 5","10.59"),DATE)
        self.assertEqual((goal[0]["under"],goal[0]["over"]),(43,57))
        row=base()
        proof=enrich_verified_rows([row],goal+corners)
        self.assertEqual(proof["ou25"],1)
        self.assertEqual(proof["corners95"],1)
        self.assertEqual(row["prediction_ou25"],"Over")
        self.assertEqual((row["prob_under25"],row["prob_over25"]),(43,57))
        self.assertEqual(row["corner_predicted_score"],"5 - 5")
        self.assertEqual(row["avg_corners"],10.59)
        self.assertEqual(row["forebet_detail_url"],URL)
        self.assertEqual((row["home"],row["draw"],row["away"]),(35,30,35))
        self.assertEqual(row["score"],"2 - 1")
    def test_unverified_identity_never_attaches(self):
        markets=parse_ou25(html_row(home="Other Home"),DATE)
        row=base()
        self.assertEqual(enrich_verified_rows([row],markets)["ou25"],0)
        self.assertNotIn("prediction_ou25",row)
    def test_league_time_and_url_must_match(self):
        for key,kw in [
            ("url",{"url":"https://www.forebet.com/en/football/matches/home-away-2999999"}),
            ("league",{"league":"It1"}),
            ("time",{"time":"10/18/2026 06:00 PM"}),
            ("order",{"home":"Sample Away","away":"Sample Home"}),
        ]:
            with self.subTest(key=key):
                row=base()
                proof=enrich_verified_rows([row],parse_ou25(html_row(**kw),DATE))
                self.assertEqual(proof["ou25"],0)
                self.assertNotIn("forebet_detail_url",row)
    def test_ambiguous_conflicting_source_market_fail_closed(self):
        row=base()
        market=parse_ou25(html_row(pick="Over")+html_row(pick="Under"),DATE)
        proof=enrich_verified_rows([row],market)
        self.assertEqual(proof["ambiguous"],1)
        self.assertNotIn("prediction_ou25",row)
    def test_duplicate_identical_market_is_safe(self):
        row=base()
        market=parse_ou25(html_row()+html_row(),DATE)
        proof=enrich_verified_rows([row],market)
        self.assertEqual(proof["ou25"],1)
    def test_incomplete_or_invalid_probabilities_are_unknown(self):
        for under,over in [(0,40),(102,0),(80,40)]:
            self.assertEqual(parse_ou25(html_row(under=under,over=over),DATE),[])
        self.assertEqual(parse_corners95(html_row(score="--"),DATE),[])
    def test_wrong_market_or_unrelated_nav_is_not_model(self):
        self.assertEqual(parse_ou25("<div class='rcnt'><span>Over 70%</span></div>",DATE),[])
        self.assertEqual(parse_ou25(html_row(url="https://evil.example/foo"),DATE),[])
    def test_corner_model_does_not_infer_from_goals(self):
        row=base()
        goal=parse_ou25(html_row(),DATE)
        enrich_verified_rows([row],goal)
        self.assertNotIn("corner_prediction",row)
        self.assertNotIn("avg_corners",row)
    def test_nonverified_primary_is_never_a_target(self):
        self.assertEqual(enrich_verified_rows([],parse_ou25(html_row(),DATE))["ou25"],0)

if __name__=="__main__": unittest.main()
