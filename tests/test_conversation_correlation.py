
import json
import tempfile
from contextlib import closing
import unittest
from pathlib import Path
import _paths  # noqa: F401  (shipped code first on sys.path)
import atlas_observability as ops

class ConversationCorrelationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = ops.DB_PATH
        ops.DB_PATH = Path(self.tmp.name) / "observability.sqlite3"

    def tearDown(self):
        ops.DB_PATH = self.old_path
        self.tmp.cleanup()

    def test_tasks_and_worker_events_are_linked_to_conversation(self):
        task = ops.submit_task({
            "type": "coding",
            "conversation_id": "chat_123",
            "bot_id": "bot_456",
            "payload": {"prompt": "test"}
        })
        self.assertEqual(task["status"], "queued")
        registration = ops.register({"name": "worker"})
        claimed = ops.claim_task(registration["agent_id"], registration["token"])
        self.assertEqual(claimed["task"]["task_id"], task["task_id"])
        self.assertTrue(ops.ingest_event(registration["agent_id"], registration["token"], {
            "task_id": task["task_id"], "trace_id": task["trace_id"],
            "kind": "model.request", "message": "Model request started"
        }))
        self.assertTrue(ops.finish_task(registration["agent_id"], registration["token"], task["task_id"], {
            "status": "completed", "result": {"ok": True}
        }))
        result = ops.conversation_diagnostics("chat_123")
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["bot_id"], "bot_456")
        kinds = [event["kind"] for event in result["events"]]
        self.assertIn("task.queued", kinds)
        self.assertIn("task.claimed", kinds)
        self.assertIn("model.request", kinds)
        self.assertIn("task.completed", kinds)

    def test_local_chat_and_mcp_events_are_persisted(self):
        ops.record_local_event("chat_123", "bot_456", "chat.request.started",
                               "Generation started", {"request_id": "req_1"})
        ops.record_local_event("chat_123", "bot_456", "mcp.tool",
                               "filesystem / read_file: EXECUTED_UNVERIFIED",
                               {"tool": "read_file"}, trace_id="req_1")
        result = ops.conversation_diagnostics("chat_123")
        self.assertEqual([e["kind"] for e in result["events"]],
                         ["chat.request.started", "mcp.tool"])
        self.assertEqual(result["events"][1]["bot_id"], "bot_456")

    def test_existing_database_schema_migrates_without_losing_rows(self):
        import sqlite3
        old = Path(self.tmp.name) / "old.sqlite3"
        c = sqlite3.connect(old)
        c.executescript("""
          CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,ts REAL NOT NULL,trace_id TEXT,span_id TEXT,parent_span_id TEXT,agent_id TEXT,task_id TEXT,level TEXT NOT NULL,kind TEXT NOT NULL,message TEXT NOT NULL,details TEXT NOT NULL DEFAULT '{}');
          CREATE TABLE tasks(task_id TEXT PRIMARY KEY,created_at REAL NOT NULL,updated_at REAL NOT NULL,status TEXT NOT NULL,priority INTEGER NOT NULL,task_type TEXT NOT NULL,payload TEXT NOT NULL,result TEXT,assigned_agent TEXT,lease_until REAL,trace_id TEXT,attempts INTEGER NOT NULL DEFAULT 0,error TEXT);
          CREATE TABLE frames(frame_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,ts REAL NOT NULL,mime TEXT NOT NULL,data BLOB NOT NULL,caption TEXT,task_id TEXT,trace_id TEXT);
          INSERT INTO events(event_id,ts,level,kind,message) VALUES('old-event',1,'info','old','keep me');
        """)
        c.commit(); c.close()
        ops.DB_PATH = old
        ops.snapshot()
        with closing(sqlite3.connect(old)) as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(events)")}
            self.assertIn("conversation_id", cols)
            self.assertIn("bot_id", cols)
            row = c.execute("SELECT message FROM events WHERE event_id='old-event'").fetchone()
            self.assertEqual(row[0], "keep me")

if __name__ == "__main__":
    unittest.main()
