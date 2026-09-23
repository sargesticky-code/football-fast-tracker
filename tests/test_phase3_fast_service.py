import threading
import time
import unittest

from phase3.fast_service import FastHeartbeatService


class FastHeartbeatServiceTests(unittest.TestCase):
    def test_many_consumers_share_one_service_refresh(self):
        calls=[]; entered=threading.Event(); release=threading.Event()
        def refresh():
            calls.append(1)
            entered.set()
            release.wait(2)
            return {
                'health':'FRESH_LIVE', 'observed_at':'2026-09-24T00:00:00+00:00',
                'snapshot_age_seconds':0.0, 'request_failures':0,
                'mapped_rows':3, 'unmapped_count':0, 'live_rows':2,
                'last_good_at':'2026-09-24T00:00:00+00:00',
            }
        service=FastHeartbeatService(refresh,lease_seconds=5)
        results=[]
        threads=[threading.Thread(target=lambda: results.append(service.read())) for _ in range(20)]
        for thread in threads: thread.start()
        self.assertTrue(entered.wait(1))
        time.sleep(.05)
        self.assertEqual(len(calls),1)
        release.set()
        for thread in threads: thread.join(2)
        self.assertEqual(len(results),20)
        self.assertEqual(len(calls),1)
        self.assertEqual(sum(r['shared_cache']['status']=='REFRESH' for r in results),1)
        self.assertTrue(all(r['health']=='FRESH_LIVE' for r in results))
        self.assertTrue(all(r['shared_cache']['upstream_refreshes']==1 for r in results))

    def test_consumer_receives_layer3_health_and_lease_diagnostics(self):
        service=FastHeartbeatService(lambda:{
            'health':'FRESH_NO_LIVE_ROWS', 'request_failures':0,
            'mapped_rows':2, 'unmapped_count':0, 'live_rows':0,
        })
        state=service.read()
        self.assertEqual(state['health'],'FRESH_NO_LIVE_ROWS')
        self.assertEqual(state['request_failures'],0)
        self.assertEqual(state['shared_cache']['status'],'REFRESH')
        self.assertEqual(state['shared_cache']['upstream_refreshes'],1)


if __name__=='__main__': unittest.main()
