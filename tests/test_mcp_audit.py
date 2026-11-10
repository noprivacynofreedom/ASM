import threading
import unittest
from collections import deque

import _paths  # noqa: F401  (shipped code first on sys.path)
from mcp_audit import MCPAuditRecorder, build_event


class MCPAuditTests(unittest.TestCase):
    def setUp(self):
        self.events = deque(maxlen=20)
        self.lock = threading.Lock()
        self.ops_rows = []
        self.recorder = MCPAuditRecorder(
            self.events, self.lock, lambda *args: self.ops_rows.append(args)
        )

    def test_preserves_monitor_evidence_and_adds_correlation(self):
        source = {
            "status": "EXECUTED_UNVERIFIED",
            "verification": "not_performed",
            "duration_ms": 0.125,
            "result": {"structuredContent": {"count": 3}},
            "timestamp": 123.5,
            "server": "demo",
            "tool": "list_items",
        }
        row = self.recorder.record(source, {
            "conversation_id": "chat-1", "bot_id": "bot-1",
            "request_id": "trace-1", "queue_job_id": "job-1",
        })
        self.assertEqual(row["result"], source["result"])
        self.assertEqual(row["duration_ms"], 0.125)
        self.assertEqual(row["verification"], "not_performed")
        self.assertEqual(row["event_type"], "mcp.tool")
        self.assertEqual(row["conversation_id"], "chat-1")
        self.assertEqual(row["trace_id"], "trace-1")
        self.assertEqual(row["queue_job_id"], "job-1")
        self.assertIs(self.events[0], row)
        self.assertEqual(len(self.ops_rows), 1)

    def test_manual_and_chat_paths_share_canonical_schema(self):
        manual = self.recorder.record(
            {"status": "VERIFIED", "server": "s", "tool": "t"},
            {"conversation_id": "manual"},
        )
        chat = self.recorder.record(
            {"status": "VERIFIED", "server": "s", "tool": "t"},
            {"conversation_id": "chat"},
        )
        self.assertEqual(set(manual), set(chat))
        self.assertEqual(manual["event_version"], 1)
        self.assertEqual(chat["event_type"], "mcp.tool")

    def test_missing_verification_is_not_claimed_verified(self):
        row = build_event({"status": "FAILED"}, {})
        self.assertEqual(row["verification"], "not_performed")

    def test_sink_failure_does_not_discard_audit_event(self):
        def broken_sink(*args):
            raise RuntimeError("OPS unavailable")
        recorder = MCPAuditRecorder(self.events, self.lock, broken_sink)
        row = recorder.record(
            {"status": "FAILED", "server": "s", "tool": "t"},
            {"conversation_id": "chat-2"},
        )
        self.assertIs(self.events[0], row)
        self.assertIn("OPS unavailable", row["audit_sink_error"])

    def test_failure_event_retains_identity_and_distinct_timings(self):
        row = build_event({
            "status": "FAILED", "server": "demo", "tool": "write",
            "duration_ms": None, "adapter_duration_ms": 0.003,
            "verification": "not_performed",
        }, {"conversation_id": "chat-3"})
        self.assertEqual(row["server"], "demo")
        self.assertEqual(row["tool"], "write")
        self.assertIsNone(row["duration_ms"])
        self.assertEqual(row["adapter_duration_ms"], 0.003)


if __name__ == "__main__":
    unittest.main()
