import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from io import BytesIO

import scripts.phase3_collect_fotmob_identity as collector


class _Response:
    def __init__(self, body: bytes): self.body=BytesIO(body)
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self,*args): return self.body.read(*args)


class SofascoreTransportTests(unittest.TestCase):
    @patch("scripts.phase3_collect_fotmob_identity.urlopen")
    def test_retries_api_host_after_www_403(self, urlopen):
        urlopen.side_effect=[
            HTTPError("https://www.sofascore.com",403,"Forbidden",{},None),
            _Response(b'{"events":[]}'),
        ]
        self.assertEqual(collector.sofascore_board("20260921"),[])
        self.assertEqual(urlopen.call_count,2)

    @patch("scripts.phase3_collect_fotmob_identity.urlopen")
    def test_raises_after_both_hosts_fail(self, urlopen):
        urlopen.side_effect=[
            HTTPError("https://www.sofascore.com",403,"Forbidden",{},None),
            HTTPError("https://api.sofascore.com",403,"Forbidden",{},None),
        ]
        with self.assertRaises(HTTPError):
            collector.sofascore_board("20260921")
        self.assertEqual(urlopen.call_count,2)


if __name__=="__main__": unittest.main()
