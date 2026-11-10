import os, sys, tempfile, unittest
os.environ["ATLAS_OBSERVABILITY_DB"] = os.path.join(tempfile.mkdtemp(), "o.sqlite3")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src-tauri", "resources", "atlas"))
import atlas_observability as OPS

class SwarmStop(unittest.TestCase):
    def test_cancel_blocks_claim_and_finish(self):
        before = OPS.task_snapshot()["counts"].get("cancelled", 0)
        a = OPS.register({"name": "w"}); aid, tok = a["agent_id"], a["token"]
        OPS.submit_task({"type": "t", "payload": {}}); OPS.submit_task({"type": "t", "payload": {}})
        task = OPS.claim_task(aid, tok)["task"]
        self.assertEqual(OPS.cancel_all_tasks(), 2)
        self.assertFalse(OPS.finish_task(aid, tok, task["task_id"], {"status": "completed"}))
        self.assertIsNone(OPS.claim_task(aid, tok)["task"])
        self.assertEqual(OPS.task_snapshot()["counts"].get("cancelled", 0) - before, 2)

if __name__ == "__main__":
    unittest.main()
