import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import _paths
ROOT = _paths.APP
sys.path.insert(0, str(ROOT))
import mcp_chat


def completion(message):
    return {"id": "test", "model": "fake", "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}]}


class FakeMonitor:
    def __init__(self): self.calls = []
    def status(self):
        return {"servers": [{"name": "atlas", "state": "online", "process_running": True,
            "tools": [{"name": "write_file", "description": "write", "inputSchema": {"type": "object", "properties": {}}}]}]}
    def call_tool(self, server, tool, args, timeout=45):
        self.calls.append((server, tool, args))
        return {"server": server, "tool": tool, "status": "EXECUTED_UNVERIFIED", "verification": "not_performed", "result": {"written": True}}


class ToolLoopTests(unittest.TestCase):
    def test_duplicate_call_is_suppressed_and_loop_completes(self):
        monitor = FakeMonitor(); audit = []; call_id = "call-1"
        responses = [
            completion({"role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "atlas__write_file", "arguments": '{"path":"a.txt"}'}}]}),
            completion({"role": "assistant", "tool_calls": [{"id": "call-2", "type": "function", "function": {"name": "atlas__write_file", "arguments": '{"path":"a.txt"}'}}]}),
            completion({"role": "assistant", "content": "The tool ran once; repeated call suppressed."}),
        ]
        with patch.object(mcp_chat, "_post_completion", side_effect=responses):
            result, events = mcp_chat.run_tool_loop({"messages": [{"role": "user", "content": "write it"}]}, monitor, audit.append, "localhost", 8080)
        self.assertIn("suppressed", result["choices"][0]["message"]["content"])
        self.assertEqual(len(monitor.calls), 1)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["status"], "FAILED")

    def test_round_limit_returns_tools_disabled_summary_not_exception(self):
        monitor = FakeMonitor(); audit = []
        tool_messages = [{"role": "assistant", "tool_calls": [{"id": f"x{i}", "type": "function", "function": {"name": "atlas__write_file", "arguments": '{"path":"file%d.txt"}' % i}}]} for i in range(3)]
        responses = [completion(m) for m in tool_messages] + [completion({"role": "assistant", "content": "Stopped at the safety limit; remaining work is unfinished."})]
        with patch.object(mcp_chat, "_post_completion", side_effect=responses) as post:
            result, events = mcp_chat.run_tool_loop({"messages": [{"role": "user", "content": "write many files"}]}, monitor, audit.append, "localhost", 8080, max_rounds=2)
        self.assertIn("unfinished", result["choices"][0]["message"]["content"])
        self.assertEqual(len(monitor.calls), 2)
        self.assertEqual(len(events), 2)
        final_payload = post.call_args_list[-1].args[2]
        self.assertNotIn("tools", final_payload)
        self.assertNotIn("tool_choice", final_payload)


if __name__ == "__main__": unittest.main(verbosity=2)
