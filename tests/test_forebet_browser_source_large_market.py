"""Offline contract for the real bounded Forebet browser-helper pipeline.

Mocks local IO only: zero Forebet HTTP, browser, Supabase or paid calls.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from forebet_browser_source import (
    load_canonical_candidates,MAX_SOURCE_BYTES,MAX_MARKET_SOURCE_BYTES,
    MAX_RENDERED_ROWS,MAX_RENDERED_ROWS_HARD,
)

URL="https://www.forebet.com/en/football-predictions/corners/2026-10-18/by-league"

def simulated(html='<div class="rcnt">A</div>', *,http=200,helper="ok",all_rows=2500):
    response=MagicMock()
    response.json.return_value={
        "status":helper,
        "solution":{"status":http,"response":html,"userAgent":"OfflineTestAgent"}
    }
    browser=MagicMock()
    context=browser.new_context.return_value
    page=context.new_page.return_value
    page.goto.return_value.status=200
    page.locator.return_value.count.return_value=5
    page.locator.return_value.first.count.return_value=0
    page.evaluate.return_value={
        "all":all_rows,"matching":1,"bytes":7_000_000,
        "mode":"allowlist_fallback",
        "fragments":['<div class="rcnt">verified only</div>']
    }
    fake_context=MagicMock()
    fake_context.__enter__.return_value.chromium.launch.return_value=browser
    return response,fake_context,page

def parse_for_test(html,date):
    return [{"date":date,"captured_match_fragment": "verified only" in html}]

class BrowserSourceSafety(unittest.TestCase):
    def capture(self,response,ctx,parser=parse_for_test):
        with patch("forebet_browser_source.requests.post",return_value=response) as fetch,patch("forebet_browser_source.sync_playwright",return_value=ctx):
            result=load_canonical_candidates(URL,"2026-10-18",[],parser=parser)
            fetch.assert_called_once()
            return result

    def test_soft_limit_1800_uses_verified_allowlist_not_empty_failure(self):
        response,ctx,page=simulated(all_rows=2500)
        rows,proof=self.capture(response,ctx)
        self.assertEqual(len(rows),1)
        self.assertEqual(proof["initial"],5)
        self.assertEqual(proof["expanded"],2500)
        self.assertEqual(proof["capture_mode"],"allowlist_fallback")
        self.assertEqual(proof["parsed_candidates"],1)
        script,params=page.evaluate.call_args.args
        self.assertIn("all.length>maxHardRows",script)
        self.assertIn("all.length<=maxRows",script)
        self.assertEqual(params["maxRows"],MAX_RENDERED_ROWS)
        self.assertEqual(params["maxHardRows"],MAX_RENDERED_ROWS_HARD)
        self.assertGreater(params["maxHardRows"],params["maxRows"])

    def test_large_initial_market_html_allowed_only_inside_bounded_cap(self):
        big='<div class="rcnt">'+' '*(MAX_SOURCE_BYTES+100)+'</div>'
        self.assertLess(len(big.encode()),MAX_MARKET_SOURCE_BYTES)
        response,ctx,_=simulated(html=big)
        rows,proof=self.capture(response,ctx)
        self.assertEqual(len(rows),1)
        self.assertEqual(proof["source_page_html_limit"],MAX_MARKET_SOURCE_BYTES)
        with patch("forebet_browser_source.requests.post",return_value=response):
            with self.assertRaisesRegex(ValueError,"FOREBET_SOURCE_RESPONSE_TOO_LARGE"):
                load_canonical_candidates(URL,"2026-10-18",[],parser=None)

    def test_invalid_http_fails_closed_instead_of_zero_corner_predictions(self):
        for status,reason in [(403,"FOREBET_SOURCE_HTTP_NOT_200"),(503,"FOREBET_SOURCE_HTTP_NOT_200")]:
            response,ctx,_=simulated(http=status)
            with self.subTest(status=status), patch("forebet_browser_source.requests.post",return_value=response):
                with self.assertRaisesRegex(ValueError,reason):
                    load_canonical_candidates(URL,"2026-10-18",[],parser=parse_for_test)

    def test_source_requires_original_model_dom(self):
        response,ctx,_=simulated(html="<div>challenge</div>")
        with patch("forebet_browser_source.requests.post",return_value=response):
            with self.assertRaisesRegex(ValueError,"FOREBET_NO_SOURCE_ROWS_IN_HTML"):
                load_canonical_candidates(URL,"2026-10-18",[],parser=parse_for_test)

    def test_hard_row_and_matching_bytes_limits_remain_fail_closed(self):
        for obj in [
            {"oversize":True,"all":MAX_RENDERED_ROWS_HARD+1},
            {"oversize":True,"all":2500,"matching":350},
        ]:
            response,ctx,page=simulated()
            page.evaluate.return_value=obj
            with self.subTest(obj=obj), patch("forebet_browser_source.requests.post",return_value=response),patch("forebet_browser_source.sync_playwright",return_value=ctx):
                with self.assertRaisesRegex(ValueError,"FOREBET_RENDERED_PAGE_OVER_HARD_LIMIT"):
                    load_canonical_candidates(URL,"2026-10-18",[],parser=parse_for_test)

if __name__=="__main__": unittest.main()
