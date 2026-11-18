"""Approval gate: read runs freely, write asks (unless ATLAS_WRITE_APPROVAL=auto),
consequential and unknown tools always ask. Deny / timeout = the call does not run."""
import ast, collections, os, pathlib, threading, time, unittest
from unittest.mock import patch

import mcp_chat
from mcp_audit import MCPAuditRecorder

ATLAS = pathlib.Path(mcp_chat.__file__).resolve().parent


def click_when_pending(approve, tool=None):
    """Play the user: wait for a pending call, then click Approve or Deny."""
    def run():
        for _ in range(200):
            rows = [r for r in mcp_chat.pending_approvals() if tool in (None, r["tool"])]
            if rows:
                mcp_chat.decide_approval(rows[0]["id"], approve)
                return
            time.sleep(0.01)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


class TierTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        os.environ.pop("ATLAS_WRITE_APPROVAL", None)

    def test_read_runs_freely(self):
        self.assertEqual(mcp_chat.approval_gate("commander", "read_workspace_file", {"path": "a"}, self.events.append, timeout=0.01),
                         (True, "auto"))
        self.assertEqual(mcp_chat.pending_approvals(), [])

    def test_write_asks_by_default(self):
        click_when_pending(True)
        self.assertEqual(mcp_chat.approval_gate("commander", "write_file", {"path": "a"}, self.events.append, timeout=5),
                         (True, "approved"))

    def test_write_auto_when_setting_says_do_not_ask(self):
        with patch.dict(os.environ, {"ATLAS_WRITE_APPROVAL": "auto"}):
            self.assertEqual(mcp_chat.approval_gate("commander", "write_file", {}, timeout=0.01), (True, "auto"))

    def test_consequential_always_asks_even_with_auto_write(self):
        with patch.dict(os.environ, {"ATLAS_WRITE_APPROVAL": "auto"}):
            self.assertEqual(mcp_chat.tool_tier("web_search"), "consequential")
            self.assertEqual(mcp_chat.approval_gate("commander", "web_search", {"query": "x"}, timeout=0.05),
                             (False, "timeout"))

    def test_unknown_tool_is_consequential(self):
        self.assertEqual(mcp_chat.tool_tier("send_email"), "consequential")
        self.assertEqual(mcp_chat.tool_tier(None), "consequential")

    def test_deny(self):
        click_when_pending(False)
        self.assertEqual(mcp_chat.approval_gate("mail", "send_email", {"to": "x"}, timeout=5), (False, "denied"))
        self.assertFalse(mcp_chat.decide_approval("no-such-id", True))

    def test_timeout_and_late_click(self):
        self.assertEqual(mcp_chat.approval_gate("mail", "send_email", {}, timeout=0.05), (False, "timeout"))
        self.assertEqual(mcp_chat.pending_approvals(), [])

    def test_audit_entry_has_no_secrets(self):
        rec = MCPAuditRecorder(collections.deque(), threading.Lock())
        mcp_chat.approval_gate("mail", "send_email", {"to": "boss", "api_key": "sk-123", "body": "x" * 300},
                               rec.record, timeout=0.01)
        row = rec.events[0]
        for key in ("tool", "tier", "args_summary", "decision", "timestamp"):
            self.assertIn(key, row)
        self.assertEqual((row["tool"], row["tier"], row["decision"]), ("send_email", "consequential", "timeout"))
        self.assertNotIn("sk-123", row["args_summary"])
        self.assertLess(len(row["args_summary"]), 200)


class FakeMonitor:
    def __init__(self):
        self.ran = []

    def status(self):
        return {"servers": [{"name": "mail", "state": "online", "process_running": True,
                             "tools": [{"name": "send_email", "inputSchema": {"type": "object", "properties": {}}}]}]}

    def call_tool(self, server, tool, args, timeout=30):
        self.ran.append(tool)
        return {"status": "EXECUTED_UNVERIFIED", "result": {"sent": True}}


class ChatLoopTests(unittest.TestCase):
    @patch("mcp_chat._post_completion")
    def test_denied_call_does_not_run_and_model_is_told(self, post):
        post.side_effect = [
            {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "mail__send_email", "arguments": "{}"}}]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "Not sent."}}]},
        ]
        monitor, events = FakeMonitor(), []
        click_when_pending(False, "send_email")
        _completion, audit = mcp_chat.run_tool_loop({"messages": [{"role": "user", "content": "mail it"}]},
                                                    monitor, events.append, "127.0.0.1", 1)
        self.assertEqual(monitor.ran, [])
        self.assertEqual(audit[0]["status"], "DENIED")
        told = post.call_args_list[1].args[2]["messages"][-1]
        self.assertEqual(told["role"], "tool")
        self.assertIn("denied", told["content"])
        self.assertTrue(any(e.get("decision") == "denied" for e in events))


class EveryPathIsGated(unittest.TestCase):
    # The transport itself and the library wrapper that only forwards to it.
    TRANSPORT = {("mcp_monitor.py", "call_tool"), ("book_tools.py", "call_tool")}

    def test_every_call_tool_caller_goes_through_the_gate(self):
        files = list(ATLAS.glob("*.py")) + list(ATLAS.glob("agents/*.py"))
        callers = []
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                names = {getattr(n.func, "attr", getattr(n.func, "id", None))
                         for n in ast.walk(fn) if isinstance(n, ast.Call)}
                if "call_tool" in names and (path.name, fn.name) not in self.TRANSPORT:
                    callers.append(f"{path.name}:{fn.name}")
                    self.assertIn("approval_gate", names, f"{path.name}:{fn.name} calls a tool without approval_gate")
        # The chat loop and the MCP panel's /api/mcp/call. A new path must be added here on purpose.
        self.assertEqual(sorted(callers), ["mcp_chat.py:_run_tool_loop", "server.py:_do_post"])


if __name__ == "__main__":
    unittest.main()
