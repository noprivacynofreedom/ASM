import tempfile, unittest
from pathlib import Path
import atlas_observability as ops
from agents.atlas_agent_runtime import AtlasAgent

class ClaimFilterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); ops.DB_PATH=Path(self.tmp.name)/'test.sqlite3'
        self.agent=ops.register({'name':'test-worker'}); self.aid=self.agent['agent_id']; self.token=self.agent['token']
    def tearDown(self): self.tmp.cleanup()
    def test_worker_only_claims_programming(self):
        ops.submit_task({'type':'inference','payload':{'x':1}})
        ops.submit_task({'type':'programming','payload':{'x':2}})
        got=ops.claim_task(self.aid,self.token,60,['programming'])['task']
        self.assertEqual(got['task_type'],'programming')
        self.assertEqual(ops.task_snapshot()['counts'].get('queued'),1)
    def test_legacy_claim_without_filter(self):
        ops.submit_task({'type':'inference','payload':{}})
        self.assertEqual(ops.claim_task(self.aid,self.token)['task']['task_type'],'inference')
    def test_expired_compatible_lease_reclaimed(self):
        task=ops.submit_task({'type':'programming','payload':{}})
        ops.claim_task(self.aid,self.token,10,['programming'])
        with ops._db() as c: c.execute("UPDATE tasks SET lease_until=0 WHERE task_id=?",(task['task_id'],))
        self.assertEqual(ops.claim_task(self.aid,self.token,60,['programming'])['task']['task_id'],task['task_id'])
    def test_invalid_filter_rejected(self):
        for value in ([],[''],['x'*81],['programming',None],'programming'):
            with self.assertRaises(ValueError): ops.claim_task(self.aid,self.token,60,value)
    def test_sdk_accepts_filter_and_rejects_bad_values(self):
        worker=AtlasAgent('http://127.0.0.1:8090','p',lambda t:{},accepted_task_types=['programming'])
        self.assertEqual(worker.accepted_task_types,['programming'])
        with self.assertRaises(ValueError): AtlasAgent('http://x','p',lambda t:{},accepted_task_types=[])

if __name__=='__main__': unittest.main()
