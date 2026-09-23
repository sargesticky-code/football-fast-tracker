import threading
import time
import unittest

from phase3.shared_fast_cache import SharedFastCache


class FakeClock:
    def __init__(self): self.value = 100.0
    def __call__(self): return self.value


class SharedFastCacheTests(unittest.TestCase):
    def test_lease_reuses_one_upstream_refresh(self):
        clock=FakeClock(); calls=[]
        cache=SharedFastCache(lambda: calls.append(1) or {'health':'FRESH_LIVE'},5,clock)
        first=cache.get(); clock.value += 4.9; second=cache.get()
        self.assertEqual(len(calls),1)
        self.assertEqual(first.cache_status,'REFRESH')
        self.assertEqual(second.cache_status,'HIT')
        self.assertAlmostEqual(second.lease_age_seconds,4.9)

    def test_expired_lease_refreshes_once(self):
        clock=FakeClock(); calls=[]
        cache=SharedFastCache(lambda: calls.append(1) or {'n':len(calls)},5,clock)
        self.assertEqual(cache.get().state['n'],1)
        clock.value += 5.0
        self.assertEqual(cache.get().state['n'],2)
        self.assertEqual(len(calls),2)

    def test_concurrent_consumers_share_singleflight_refresh(self):
        calls=[]; entered=threading.Event(); release=threading.Event()
        def refresh():
            calls.append(1); entered.set(); release.wait(2); return {'health':'FRESH_LIVE','live_rows':2}
        cache=SharedFastCache(refresh,5)
        results=[]
        threads=[threading.Thread(target=lambda: results.append(cache.get())) for _ in range(12)]
        for t in threads: t.start()
        self.assertTrue(entered.wait(1)); time.sleep(.05)
        self.assertEqual(len(calls),1)
        release.set()
        for t in threads: t.join(2)
        self.assertEqual(len(results),12)
        self.assertEqual(len(calls),1)
        self.assertEqual(sum(r.cache_status=='REFRESH' for r in results),1)
        self.assertTrue(all(r.state['live_rows']==2 for r in results))

    def test_refresh_error_preserves_previous_state(self):
        clock=FakeClock(); calls=[]
        def refresh():
            calls.append(1)
            if len(calls)==1: return {'health':'FRESH_LIVE','live_rows':1}
            raise RuntimeError('temporary source failure')
        cache=SharedFastCache(refresh,5,clock)
        good=cache.get(); clock.value += 6
        fallback=cache.get()
        self.assertEqual(good.state,fallback.state)
        self.assertEqual(fallback.cache_status,'STALE_AFTER_ERROR')
        self.assertGreaterEqual(fallback.lease_age_seconds,6)
        self.assertEqual(len(calls),2)

    def test_consumer_mutation_cannot_corrupt_shared_state(self):
        cache=SharedFastCache(lambda:{'rows':[{'score':'1-0'}]},5)
        one=cache.get(); one.state['rows'][0]['score']='9-9'
        self.assertEqual(cache.get().state['rows'][0]['score'],'1-0')


if __name__=='__main__': unittest.main()
