import unittest

from phase3.fotmob_heavy_source import FotMobHeavySource


class _Response:
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.body


class FotMobHeavySourceTests(unittest.TestCase):
    def test_one_fetch_is_exactly_one_match_details_request(self):
        calls = []
        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            return _Response(b'{"content":{"stats":{}}}')
        source = FotMobHeavySource(opener=opener, timeout_seconds=7)
        payload = source.fetch_json("123456")
        self.assertIn("content", payload)
        self.assertEqual(1, len(calls))
        self.assertIn("matchId=123456", calls[0][0])
        self.assertEqual(7.0, calls[0][1])
        self.assertEqual({"requests_attempted": 1, "requests_succeeded": 1, "requests_failed": 0}, source.diagnostics.as_dict())

    def test_failure_is_counted_and_not_retried_here(self):
        calls = []
        def opener(request, timeout):
            calls.append(request.full_url)
            raise TimeoutError("source timeout")
        source = FotMobHeavySource(opener=opener)
        with self.assertRaises(TimeoutError):
            source.fetch_json("987")
        self.assertEqual(1, len(calls))
        self.assertEqual({"requests_attempted": 1, "requests_succeeded": 0, "requests_failed": 1}, source.diagnostics.as_dict())

    def test_invalid_id_fails_before_network(self):
        calls = []
        source = FotMobHeavySource(opener=lambda *a, **k: calls.append(1))
        with self.assertRaises(ValueError):
            source.fetch_json("not-an-id")
        self.assertEqual([], calls)
        self.assertEqual(0, source.diagnostics.requests_attempted)


if __name__ == "__main__":
    unittest.main()
