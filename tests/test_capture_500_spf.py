import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from capture_500_spf import read_official,resolve_canonical

NOW=datetime(2026,10,10,12,25,tzinfo=timezone.utc)
FIXTURES=[
 {"id":"FB6342","kickoff":"2026-10-10T11:30:00Z","home":"Arsenal","away":"Leeds","league":"EPL"},
 {"id":"FB6346","kickoff":"2026-10-10T14:00:00Z","home":"Chelsea","away":"Bournemouth","league":"EPL"},
]
XML=b'<root><m id="2041867" matchnum="6005" league="\xe8\x8b\xb1\xe6\xa0\xbc\xe5\x85\xb0\xe8\xb6\x85\xe7\xba\xa7\xe8\x81\x94\xe8\xb5\x9b" home="\xe9\x98\xbf\xe6\xa3\xae\xe7\xba\xb3" away="\xe5\x88\xa9\xe5\x85\xb9\xe8\x81\x94"><row win="2.02" draw="3.50" lost="2.87" updatetime="2026-10-10 19:54"/></m></root>'
HTML='<table><tr data-processname="6005" data-id="2041867" data-matchdate="2026-10-10" data-matchtime="19:30"></tr></table>'
class ProviderTests(unittest.TestCase):
 def test_exact_join_and_prices(self):
  rows=read_official(XML,HTML,NOW)
  self.assertEqual(len(rows),1)
  self.assertEqual(rows[0]["source_event_id"],"2041867")
  self.assertEqual(rows[0]["home"],2.02)
  self.assertEqual(rows[0]["kickoff"],"2026-10-10T11:30:00+00:00")
  self.assertEqual(resolve_canonical(rows,FIXTURES,NOW)[0]["match_id"],"FB6342")
 def test_wrong_provider_event_id(self):
  self.assertEqual(read_official(XML,HTML.replace("2041867","99999"),NOW),[])
 def test_reversed_fixture_never_matches(self):
  rows=read_official(XML,HTML,NOW)
  bad=[dict(FIXTURES[0],home="Leeds",away="Arsenal")]
  self.assertEqual(resolve_canonical(rows,bad,NOW),[])
 def test_time_drift_rejected(self):
  rows=read_official(XML,HTML,NOW)
  changed=[dict(FIXTURES[0],kickoff="2026-10-10T13:00:00Z")]
  self.assertEqual(resolve_canonical(rows,changed,NOW),[])
 def test_ambiguous_alias_rejected(self):
  rows=read_official(XML,HTML,NOW)
  self.assertEqual(resolve_canonical(rows,[dict(FIXTURES[0],id="FB1"),dict(FIXTURES[0],id="FB2")],NOW),[])
 def test_price_below_1_01_rejected(self):
  self.assertEqual(read_official(XML.replace(b'win="2.02"',b'win="0.0"'),HTML,NOW),[])
 def test_non_epl_rejected(self):
  rows=read_official(XML.replace("英格兰超级联赛".encode(), "法国甲级联赛".encode()),HTML,NOW)
  self.assertEqual(resolve_canonical(rows,FIXTURES,NOW),[])
 def test_stale_timestamp_future_rejected(self):
  self.assertEqual(read_official(XML.replace(b'2026-10-10 19:54',b'2026-10-11 19:54'),HTML,NOW),[])
 def test_duplicate_index_rejected(self):
  self.assertEqual(read_official(XML,HTML.replace('</table>','<tr data-processname="6005" data-id="2041867" data-matchdate="2026-10-10" data-matchtime="19:30"></tr></table>'),NOW),[])
if __name__=="__main__":unittest.main()
