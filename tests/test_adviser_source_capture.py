import unittest
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
from scripts.adviser_source_capture import parse_betclan, parse_sportytrader, candidate_urls, valid_triplet
from scripts.adviser_source_capture import collect
from scripts.adviser_source_capture import enrich_sportytrader_event
from scripts.adviser_source_capture import replay_saved_evidence


class BoundedSourceEvidenceTest(unittest.TestCase):
    def test_saved_replay_keeps_capture_time_and_rejects_changed_evidence_without_network(self):
        html = '<h1>QPR vs Derby Prediction</h1><p>16/10/2026 07:45</p>'
        digest = hashlib.sha256(html.encode()).hexdigest()
        report = {'generated_at':'2026-10-15T17:15:06Z','records':[{'source':'SPORTYTRADER','source_event_id':'123',
                  'source_url':'https://www.sportytrader.com/en/betting-tips/qpr-derby-123/',
                  'captured_at':'2026-10-15T17:15:06Z','raw_content_hash':digest}]}
        with tempfile.TemporaryDirectory() as directory, patch('scripts.adviser_source_capture.fetch') as fetch:
            path=Path(directory)/'sportytrader'/(digest+'.html');path.parent.mkdir();path.write_text(html)
            replay = replay_saved_evidence(report,directory)
            self.assertEqual(replay['generated_at'],report['generated_at'])
            self.assertEqual(replay['records'][0]['captured_at'],report['records'][0]['captured_at'])
            path.write_text(html+' changed')
            with self.assertRaisesRegex(ValueError,'hash_mismatch'):
                replay_saved_evidence(report,directory)
            fetch.assert_not_called()

    def test_source_linked_event_verifies_only_identical_oriented_clock_and_competition(self):
        import json
        # Saved live source artifact11994040671 / run38775736633.
        url = 'https://www.sportytrader.com/en/results-live/aberdeen-st-mirren-8556351/'
        row = {'source':'SPORTYTRADER','home':'Aberdeen','away':'St Mirren','source_date':'2026-10-17',
               'source_wall_time':'09:00','source_competition':'Scottish Premiership','kickoff_timezone_verified':False}
        event = {'@type':'SportsEvent','url':url,'startDate':'2026-10-17T09:00:00-05:00',
                 'homeTeam':{'name':'Aberdeen'},'awayTeam':{'name':'St Mirren'},'organizer':{'name':'Scottish Premiership'}}
        def page(events): return '<script type="application/ld+json">'+json.dumps(events)+'</script>'
        result = enrich_sportytrader_event(row,page([event]),url)
        self.assertTrue(result['kickoff_timezone_verified'])
        self.assertEqual(result['source_kickoff'],'2026-10-17T09:00:00-05:00')
        self.assertIsNone(result['source_event_status'])  # Not invented from a successful capture.
        for changed in [dict(event,startDate='2026-10-17T09:00:00'),dict(event,startDate='2026-10-17T10:00:00-05:00'),
                        dict(event,url=url.replace('8556351','999')),dict(event,homeTeam=event['awayTeam'],awayTeam=event['homeTeam']),
                        dict(event,organizer={'name':'Other league'})]:
            self.assertFalse(enrich_sportytrader_event(row,page([changed]),url)['kickoff_timezone_verified'])
        self.assertFalse(enrich_sportytrader_event(row,page([event,event]),url)['kickoff_timezone_verified'])

    def test_targeted_capture_preserves_replayable_html_without_other_provider_requests(self):
        html = '<h1>QPR vs Derby County Prediction</h1><p>16/10/2026 07:45</p><p>Prediction : BTTS 1.83</p>'
        calls = []
        def fake_fetch(session, url):
            calls.append(url)
            if url.endswith('-378837/'):
                return html
            return '<a href="/en/betting-tips/qpr-derby-county-378837/">tip</a><a href="/en/betting-tips/zz-other-378838/">other</a>'
        with tempfile.TemporaryDirectory() as directory, patch('scripts.adviser_source_capture.fetch', side_effect=fake_fetch):
            result = collect(source='SPORTYTRADER', limit=1, pause=0, evidence_dir=directory)
            self.assertEqual(len(result['records']), 1)
            self.assertTrue(all('sportytrader.com' in url for url in calls))
            self.assertEqual(len(calls), 3)  # Two listings, one deduplicated detail.
            digest = hashlib.sha256(html.encode()).hexdigest()
            self.assertEqual(result['records'][0]['raw_content_hash'], digest)
            self.assertEqual((Path(directory)/'sportytrader'/(digest+'.html')).read_text(), html)
            self.assertFalse(result['records'][0]['kickoff_timezone_verified'])

    def test_invalid_bounds_reject_before_network(self):
        for kwargs in ({'limit':0}, {'limit':121}, {'source':'UNKNOWN'}, {'related_evidence_limit':9}, {'related_evidence_limit':1}):
            with self.assertRaises(ValueError), patch('scripts.adviser_source_capture.fetch') as fetch:
                collect(**kwargs)
            fetch.assert_not_called()

    def test_related_evidence_is_explicit_bounded_and_does_not_verify_kickoff(self):
        html = '<h1>QPR vs Derby Prediction</h1><p>16/10/2026 07:45</p><a href="/en/results-live/qpr-derby-123/">Live</a>'
        related_html = '<script type="application/ld+json">{"@type":"SportsEvent","startDate":"2026-10-16T19:45:00Z"}</script>'
        def fake_fetch(session, url):
            if '/results-live/' in url:
                return related_html
            if url.endswith('-378837/'):
                return html
            return '<a href="/en/betting-tips/qpr-derby-378837/">tip</a>'
        with tempfile.TemporaryDirectory() as directory, patch('scripts.adviser_source_capture.fetch', side_effect=fake_fetch) as fetch:
            result = collect(source='SPORTYTRADER', limit=1, pause=0, evidence_dir=directory, related_evidence_limit=1)
            self.assertEqual(fetch.call_count, 4)
            row = result['records'][0]
            digest = hashlib.sha256(related_html.encode()).hexdigest()
            self.assertEqual(row['related_content_hash'], digest)
            self.assertEqual((Path(directory)/'sportytrader-related'/(digest+'.html')).read_text(), related_html)
            self.assertFalse(row['kickoff_timezone_verified'])


class AdviserSourceCaptureTest(unittest.TestCase):
    def test_betclan_genuine_detail_shape(self):
        html = """<h1>QPR vs Derby Prediction, H2H, Tip and Match Preview</h1>
        <p>Date 2026-10-14 19:45</p><h4>Winner</h4>
        <p>QPR Home 57% Draw 23% Away 20%</p>
        <h4>Total Goals 2.5</h4><p>Under 44% Over 56%</p>
        <h4>Both Teams to Score BTTS</h4><p>Yes 58% No 42%</p>
        <h4>Correct Score</h4><p>3-1 13% Others 87%</p>
        <h3>Team Momentum</h3>"""
        row = parse_betclan(html, "https://www.betclan.com/predictionsdetails/football/1563202/qpr-v-derby-prediction/")
        self.assertEqual(row["hda"], {"home": 0.57, "draw": 0.23, "away": 0.2})
        self.assertEqual(row["predicted_score"], "3-1")
        self.assertEqual(row["over25"], 0.56)
        self.assertEqual(row["btts_yes"], 0.58)
        self.assertIsNone(row["canonical_event_id"])
        self.assertFalse(row["kickoff_timezone_verified"])

    def test_sportytrader_tip_is_not_fake_probability(self):
        html = """<h1>QPR vs Derby County Prediction & Betting Tips - Championship</h1>
          <div>15/10/2026 07:45</div><p>Prediction : BTTS 1.83</p>
          <p>Prediction published on 14/10/2026</p>"""
        row = parse_sportytrader(html, "https://www.sportytrader.com/en/betting-tips/qpr-derby-county-378837/")
        self.assertEqual(row["tip"], "BTTS")
        self.assertEqual(row["source_date"], "2026-10-15")
        self.assertIsNone(row["hda"])
        self.assertEqual(row["identity"], "UNRESOLVED")


    def test_sportytrader_verified_algorithm_not_bookmaker_odds(self):
        html = """<h1>QPR vs Derby County Prediction & Betting Tips - Championship</h1>
          <div>15/10/2026 07:45</div><p>Prediction : Under 2.5 goals 1.83</p>
          <p>Prediction published on 14/10/2026</p>
          <p>Probabilities according to our algorithm of possible 1X2 football predictions
          The Sportytrader algorithm estimates a probability of 43.66% for a win of QPR.
          The probability according to Sportytrader for a draw between QPR vs Derby County is 36.64%.
          Our prediction model gives a 19.71% chance for a win of Derby County vs QPR.
          </p><h3>QPR - Derby County Prediction and Best Odds:</h3>"""
        row = parse_sportytrader(html, "https://www.sportytrader.com/en/betting-tips/qpr-derby-county-378837/")
        self.assertEqual(row["tip"], "Under 2.5 goals")
        self.assertEqual(row["hda"], {"home": .4366, "draw": .3664, "away": .1971})
        self.assertIsNone(row["canonical_event_id"])

    def test_source_boundary(self):
        html = """<a href="/predictionsdetails/football/123/abc">One</a>
           <a href="https://evil.test/predictionsdetails/football/999/bad">Evil</a>"""
        self.assertEqual(len(candidate_urls(html, "BETCLAN")), 1)

    def test_wrong_probability_triplet_rejected(self):
        self.assertIsNone(valid_triplet({"home": .8, "draw": .4, "away": .3}))


if __name__ == "__main__":
    unittest.main()

class BetClanRegressionTest(unittest.TestCase):
    def page(self, start='2026-10-15T00:30:00+01:00'):
        import json
        event={'@type':'SportsEvent','url':'https://www.betclan.com/predictionsdetails/football/123/test/',
               'startDate':start,'homeTeam':{'name':'Home'},'awayTeam':{'name':'Away'},
               'organizer':{'name':'Estonia Meistriliiga'}}
        return '''<nav>Correct Score Calculator</nav><h1>Home vs Away Prediction</h1>
        <p>Date 2026-10-15 00:30</p><h4>Winner</h4><p>Home 60% Draw 20% Away 20%</p>
        <h4>Total Goals 2.5</h4><p>Over 63%</p><h4>Both Teams to Score</h4><p>Yes 61%</p>
        <h4>Correct Score</h4><h5>3-1</h5><h3>Team Momentum</h3>
        <script type="application/ld+json">'''+json.dumps(event)+'</script>'

    def test_navigation_date_is_never_score(self):
        row=parse_betclan(self.page(),'https://www.betclan.com/predictionsdetails/football/123/test/')
        self.assertEqual(row['predicted_score'],'3-1')
        self.assertEqual(row['source_kickoff'],'2026-10-15T00:30:00+01:00')
        self.assertTrue(row['kickoff_timezone_verified'])
        self.assertEqual(row['source_competition'],'Estonia Meistriliiga')

    def test_missing_market_stays_unknown(self):
        row=parse_betclan(self.page().replace('<h4>Correct Score</h4><h5>3-1</h5>',''),
                         'https://www.betclan.com/predictionsdetails/football/123/test/')
        self.assertIsNone(row['predicted_score'])

    def test_timezone_missing_or_conflicting_stays_unknown(self):
        for at in ['2026-10-15T00:30:00','2026-10-14T00:30:00+01:00']:
            row=parse_betclan(self.page(at),'https://www.betclan.com/predictionsdetails/football/123/test/')
            self.assertIsNone(row['source_kickoff'])
            self.assertFalse(row['kickoff_timezone_verified'])

    def test_bad_triplets(self):
        for triplet in [{'home':-.1,'draw':.5,'away':.6},{'home':float('nan'),'draw':.5,'away':.5},
                        {'home':True,'draw':0,'away':0},{'home':1.1,'draw':0,'away':-.1}]:
            self.assertIsNone(valid_triplet(triplet))
