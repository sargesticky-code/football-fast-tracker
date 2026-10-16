"""Fail-closed source-only extraction tests; no network, no betting, no writes."""
import unittest
from datetime import date
from unittest.mock import Mock
from scripts.additional_adviser_sources import (
    parse_primatips, parse_statarea, fetch, collect
)


class AdditionalAdviserSourcesTests(unittest.TestCase):

    def test_primatips_real_hda_not_bookmaker_odds(self):
        html = """<h1>Friday, October 16, 2026</h1>
        <a id="g_949885" class="game"
          href="https://primatips.com/tip/huracan-gimnasia-liga-949885">
          <span class="tf"><span class="tm">19:45</span>
          <span class="fl"><img title="Argentina - Liga Profesional"></span></span>
          <span class="nms"><span class="nm">Huracan</span> -
          <span class="nm">Gimnasia LP</span></span>
          <span class="data"><span class="tos"><span class="ts">
          <span class="t">35</span><span class="t">33</span><span class="t">32</span></span>
          <span class="os"><span class="o">2.40</span><span class="o">3.10</span>
          <span class="o">3.10</span></span></span>
          <span class="to"><span class="tip">1X</span></span></a>"""
        rows = parse_primatips(html, "2026-10-16")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["source_event_id"], "949885")
        self.assertEqual(r["hda"], {"home": 0.35, "draw": 0.33, "away": 0.32})
        self.assertEqual(r["source_average_1x2_odds"]["home"], 2.4)
        self.assertIsNone(r["source_kickoff"])
        self.assertFalse(r["kickoff_timezone_verified"])
        self.assertEqual(r["source_competition"], "Argentina - Liga Profesional")
        self.assertEqual(r["identity_status"], "UNRESOLVED")

    def test_primatips_fail_closed_if_date_or_event_identity_fails(self):
        html = """<h1>Friday, October 16, 2026</h1>
        <a id="g_111111" class="game"
          href="https://primatips.com/tip/home-away-222222">
          <span class="tm">10:00</span><span class="fl"><img title="Premier League"></span>
          <span class="nms"><span class="nm">Home</span><span class="nm">Away</span></span>
          <span class="data"><span class="tos"><span class="ts">
          <span class="t">50</span><span class="t">30</span><span class="t">20</span>
          </span></span></span></a>"""
        self.assertEqual(parse_primatips(html, "2026-10-16"), [])
        with self.assertRaisesRegex(ValueError, "DATE_MISMATCH"):
            parse_primatips(html, "2026-10-17")

    def test_statarea_real_markets_without_fake_kickoff(self):
        labels = ["1","X","2","H1","HX","H2","1.5","2.5","3.5","BTS","OTS"]
        pcts = [50,28,22,27,54,19,80,61,34,56,44]
        html = ("""<table><tr><td colspan="11">All predictions for  2026-10-16</td></tr>
        <tr><td><img alt="Spain"></td><td colspan="10">Spain-Laliga2</td></tr>
        <tr><td colspan="11">time: 21:30</td></tr>
        <tr><td colspan="10">prediction: <b>1</b></td><td>&nbsp;</td></tr>
        <tr><td colspan="10">Leganes</td><td>-</td></tr>
        <tr><td colspan="10">Cordoba</td><td>-</td></tr>
        <tr>""" +
        "".join("<td>" + x + "</td>" for x in labels) + "</tr><tr>" +
        "".join("<td>" + str(x) + "%</td>" for x in pcts) + "</tr></table>")
        rows = parse_statarea(html, "2026-10-16")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["hda"], {"home": 0.5, "draw": 0.28, "away": 0.22})
        self.assertEqual(r["source_home"], "Leganes")
        self.assertEqual(r["source_away"], "Cordoba")
        self.assertEqual(r["source_competition"], "Spain-Laliga2")
        self.assertEqual(r["over25"], 0.61)
        self.assertEqual(r["btts_yes"], 0.56)
        self.assertEqual(r["event_id_basis"], "OBSERVATION_HASH_NOT_PROVIDER_ID")
        self.assertIsNone(r["source_kickoff"])
        self.assertFalse(r["kickoff_timezone_verified"])
        with self.assertRaisesRegex(ValueError, "DATE_MISMATCH"):
            parse_statarea(html, "2026-10-17")

    def test_no_unknown_hosts_ever_contacted(self):
        session = Mock()
        with self.assertRaisesRegex(ValueError, "HOST_NOT_ALLOWED"):
            fetch(session, "https://evil.example/collect")
        session.get.assert_not_called()

    def test_empty_or_unavailable_page_is_not_success(self):
        session = Mock()
        response = Mock()
        response.text = "<h1>No predictions</h1>"
        response.content = response.text.encode()
        response.url = "https://primatips.com/tips/2026-10-16"
        session.get.return_value = response
        report = collect(date(2026,10,16),session)
        self.assertEqual(report["providers"]["PRIMATIPS"]["successful_dates"],0)
        self.assertEqual(report["providers"]["STATAREA"]["successful_dates"],0)
        self.assertEqual(report["records"],[])
        self.assertFalse(report["publication_enabled"])


if __name__ == "__main__":
    unittest.main()
