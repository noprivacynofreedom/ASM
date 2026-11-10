"""Regression tests for the MCP-to-chat adapter and safety boundaries."""
import unittest
from unittest.mock import patch

import _paths  # noqa: F401  (shipped code first on sys.path)
import mcp_chat


class FakeMonitor:
    def __init__(self, name="safe-files", tool="list_files", schema=None):
        self.server_name = name
        self.tool_name = tool
        self.schema = schema or {"type": "object", "properties": {}}
        self.calls = []

    def status(self):
        return {"servers": [{
            "name": self.server_name, "state": "online", "process_running": True,
            "tools": [{"name": self.tool_name, "description": "List files", "inputSchema": self.schema}],
        }]}

    def call_tool(self, server, tool, args, timeout=30):
        self.calls.append((server, tool, args, timeout))
        return {"server": server, "tool": tool, "status": "EXECUTED_UNVERIFIED",
                "verification": "not_performed",
                "result": {"content": [{"type": "text", "text": "file-a.py"}]}}


class MCPChatTests(unittest.TestCase):
    @patch("mcp_chat._post_completion")
    def test_tool_call_executes_and_result_returns_to_model(self, post):
        post.side_effect = [
            {"choices": [{"message": {"role": "assistant", "content": None,
             "tool_calls": [{"id": "call-1", "type": "function", "function": {
                 "name": "safe-files__list_files", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]},
            {"choices": [{"message": {"role": "assistant", "content": "I found file-a.py."}, "finish_reason": "stop"}]},
        ]
        monitor, audit = FakeMonitor(), []
        result, events = mcp_chat.run_tool_loop(
            {"messages": [{"role": "user", "content": "List files"}], "stream": True},
            monitor, audit.append, "127.0.0.1", 8080,
        )
        self.assertEqual(result["choices"][0]["message"]["content"], "I found file-a.py.")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "EXECUTED_UNVERIFIED")
        self.assertEqual(audit, events)
        self.assertEqual(monitor.calls[0][1], "list_files")
        sent = post.call_args_list[1].args[2]["messages"]
        self.assertEqual(sent[-2]["role"], "assistant")
        self.assertEqual(sent[-2]["tool_calls"][0]["id"], "call-1")
        self.assertEqual(sent[-1]["role"], "tool")
        self.assertEqual(sent[-1]["tool_call_id"], "call-1")
        self.assertIn("file-a.py", sent[-1]["content"])

    def test_tool_names_are_sanitized_and_mapped_back(self):
        monitor = FakeMonitor(name="files server.with spaces", tool="read/path" + "x" * 80)
        tools, lookup = mcp_chat._tool_definitions(monitor)
        name = tools[0]["function"]["name"]
        self.assertLessEqual(len(name), 64)
        self.assertRegex(name, r"^[A-Za-z0-9_-]+$")
        self.assertEqual(lookup[name], (monitor.server_name, monitor.tool_name))

    def test_schema_is_bounded_and_preserves_enum_and_property_names(self):
        schema = {
            "type": "object", "$schema": "ignored",
            "properties": {"file/path": {"type": "string", "enum": ["a", "b"], "x-vendor": True}},
            "required": ["file/path"],
        }
        safe = mcp_chat._safe_schema(schema)
        self.assertIn("file/path", safe["properties"])
        self.assertEqual(safe["properties"]["file/path"]["enum"], ["a", "b"])
        self.assertNotIn("$schema", safe)
        self.assertNotIn("x-vendor", safe["properties"]["file/path"])

    @patch("mcp_chat._post_completion")
    def test_malformed_arguments_never_execute_empty_arguments(self, post):
        post.side_effect = [
            {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": "bad-1", "function": {"name": "safe-files__list_files", "arguments": "{bad"}}
            ]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "The tool arguments were invalid."}}]},
        ]
        monitor, audit = FakeMonitor(), []
        result, events = mcp_chat.run_tool_loop(
            {"messages": [{"role": "user", "content": "List"}]},
            monitor, audit.append, "localhost", 8080,
        )
        self.assertEqual(monitor.calls, [])
        self.assertEqual(events[0]["status"], "FAILED")
        self.assertIn("Invalid JSON", events[0]["error"])
        self.assertIn("Invalid JSON", post.call_args_list[1].args[2]["messages"][-1]["content"])

    @patch("mcp_chat._post_completion")
    def test_duplicate_operation_suppressed_even_with_new_call_id(self, post):
        call1 = {"id": "call-1", "type": "function", "function": {"name": "safe-files__list_files", "arguments": "{}"}}
        call2 = {"id": "call-2", "type": "function", "function": {"name": "safe-files__list_files", "arguments": "{}"}}
        post.side_effect = [
            {"choices": [{"message": {"role": "assistant", "tool_calls": [call1]}}]},
            {"choices": [{"message": {"role": "assistant", "tool_calls": [call2]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "One operation ran."}}]},
        ]
        monitor = FakeMonitor()
        result, events = mcp_chat.run_tool_loop(
            {"messages": [{"role": "user", "content": "List twice"}]},
            monitor, lambda event: None, "localhost", 8080, max_rounds=4,
        )
        self.assertEqual(len(monitor.calls), 1)
        self.assertTrue(events[1]["duplicate_suppressed"])
        self.assertEqual(result["choices"][0]["message"]["content"], "One operation ran.")

    @patch("mcp_chat._post_completion")
    def test_empty_answer_recovery_removes_tools_and_private_reasoning(self, post):
        post.side_effect = [
            {"choices": [{"message": {"role": "assistant", "content": "", "reasoning_content": "private"}}]},
            {"choices": [{"message": {"role": "assistant", "content": "Recovered answer."}}]},
        ]
        result, _ = mcp_chat.run_tool_loop(
            {"messages": [{"role": "user", "content": "Explain"}], "max_tokens": "32"},
            FakeMonitor(), lambda event: None, "localhost", 8080,
        )
        retry = post.call_args_list[1].args[2]
        self.assertNotIn("tools", retry)
        self.assertNotIn("tool_choice", retry)
        self.assertNotIn("reasoning_content", str(retry["messages"]))
        self.assertEqual(retry["max_tokens"], 1024)
        self.assertEqual(result["choices"][0]["message"]["content"], "Recovered answer.")

    @patch("mcp_chat._post_completion")
    def test_round_limit_forces_text_only_and_never_executes_extra_call(self, post):
        tool_message = {"role": "assistant", "tool_calls": [
            {"id": "c1", "function": {"name": "safe-files__list_files", "arguments": "{}"}}
        ]}
        post.side_effect = [
            {"choices": [{"message": tool_message}]},
            {"choices": [{"message": tool_message}]},
        ]
        monitor = FakeMonitor()
        result, events = mcp_chat.run_tool_loop(
            {"messages": [{"role": "user", "content": "List"}]},
            monitor, lambda event: None, "localhost", 8080, max_rounds=1,
        )
        final_request = post.call_args_list[-1].args[2]
        self.assertNotIn("tools", final_request)
        self.assertNotIn("tool_choice", final_request)
        self.assertNotIn("tool_calls", result["choices"][0]["message"])
        self.assertTrue(result["choices"][0]["message"]["content"])
        self.assertEqual(len(monitor.calls), 1)

    @patch("mcp_chat._post_completion")
    def test_audit_sink_failure_does_not_discard_tool_result(self, post):
        post.side_effect = [
            {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": "call-1", "function": {"name": "safe-files__list_files", "arguments": "{}"}}
            ]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "Completed."}}]},
        ]
        result, events = mcp_chat.run_tool_loop(
            {"messages": [{"role": "user", "content": "List"}]},
            FakeMonitor(), lambda event: (_ for _ in ()).throw(OSError("audit disk unavailable")),
            "localhost", 8080,
        )
        self.assertIn("audit_record_error", events[0])
        self.assertEqual(result["choices"][0]["message"]["content"], "Completed.")



    @patch("mcp_chat._post_completion")
    def test_successful_final_response_strips_private_reasoning(self, post):
        post.return_value = {"choices": [{"message": {
            "role": "assistant", "content": "Visible answer.", "reasoning_content": "private trace"
        }}]}
        result, _ = mcp_chat.run_tool_loop(
            {"messages": [{"role": "user", "content": "Explain"}]},
            FakeMonitor(), lambda event: None, "localhost", 8080,
        )
        message = result["choices"][0]["message"]
        self.assertEqual(message["content"], "Visible answer.")
        self.assertNotIn("reasoning_content", message)

    @patch("mcp_chat._post_completion")
    def test_missing_tool_call_id_is_repaired_in_assistant_message(self, post):
        post.side_effect = [
            {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"type": "function", "function": {"name": "safe-files__list_files", "arguments": "{}"}}
            ]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "Done."}}]},
        ]
        result, _ = mcp_chat.run_tool_loop(
            {"messages": [{"role": "user", "content": "List"}]},
            FakeMonitor(), lambda event: None, "localhost", 8080,
        )
        sent = post.call_args_list[1].args[2]["messages"]
        assistant_call_id = sent[-2]["tool_calls"][0]["id"]
        tool_call_id = sent[-1]["tool_call_id"]
        self.assertTrue(assistant_call_id.startswith("call_atlas_"))
        self.assertEqual(assistant_call_id, tool_call_id)

    @patch("mcp_chat._post_completion")
    def test_non_object_arguments_are_rejected(self, post):
        post.side_effect = [
            {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": "bad-2", "function": {"name": "safe-files__list_files", "arguments": "[]"}}
            ]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "Invalid args rejected."}}]},
        ]
        monitor = FakeMonitor()
        _, events = mcp_chat.run_tool_loop(
            {"messages": [{"role": "user", "content": "List"}]},
            monitor, lambda event: None, "localhost", 8080,
        )
        self.assertEqual(monitor.calls, [])
        self.assertIn("JSON object", events[0]["error"])

    def test_sse_encoder_handles_text_content_and_done_marker(self):
        response = {"id": "x", "model": "test", "choices": [{"message": {"content": [{"type": "text", "text": "hello"}]}, "finish_reason": "stop"}]}
        stream = mcp_chat.as_sse(response)
        self.assertIn('"content": "hello"', stream)
        self.assertTrue(stream.endswith("data: [DONE]\n\n"))

    def test_existing_tool_name_collision_is_avoided(self):
        monitor = FakeMonitor()
        reserved = {"safe_files__list_files"}
        tools, lookup = mcp_chat._tool_definitions(monitor, reserved)
        name = tools[0]["function"]["name"]
        self.assertNotEqual(name, "safe_files__list_files")
        self.assertIn(name, lookup)



    @patch("mcp_chat._post_completion")
    def test_chat_audit_preserves_monitor_evidence_and_separate_adapter_timing(self, post):
        post.side_effect = [
            {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": "evidence-1", "function": {
                    "name": "safe-files__list_files", "arguments": "{}"
                }}
            ]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "Completed."}}]},
        ]

        class EvidenceMonitor(FakeMonitor):
            def call_tool(self, server, tool, args, timeout=30):
                return {
                    "server": server,
                    "tool": tool,
                    "status": "EXECUTED_UNVERIFIED",
                    "verification": "not_performed",
                    "duration_ms": 0.375,
                    "result": {"structuredContent": {"items": ["a.py"]}},
                    "timestamp": 1234.5,
                }

        audit = []
        _, events = mcp_chat.run_tool_loop(
            {"messages": [{"role": "user", "content": "List files"}]},
            EvidenceMonitor(), audit.append, "localhost", 8080,
        )
        event = events[0]
        self.assertEqual(event["duration_ms"], 0.375)
        self.assertEqual(event["verification"], "not_performed")
        self.assertEqual(event["result"], {"structuredContent": {"items": ["a.py"]}})
        self.assertEqual(event["timestamp"], 1234.5)
        self.assertIsInstance(event["adapter_duration_ms"], float)
        self.assertGreaterEqual(event["adapter_duration_ms"], 0)
        self.assertEqual(audit[0]["duration_ms"], 0.375)


if __name__ == "__main__":
    unittest.main()
