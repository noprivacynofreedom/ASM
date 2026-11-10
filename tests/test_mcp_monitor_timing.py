import json
import pathlib
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest.mock import patch

import _paths  # noqa: F401  (shipped code first on sys.path)
from mcp_monitor import MCPConnection, MCPMonitor


class _Process:
    def poll(self):
        return None


class MCPMonitorTimingTests(unittest.TestCase):
    def test_tool_duration_preserves_sub_millisecond_precision(self):
        connection = MCPConnection.__new__(MCPConnection)
        connection.lock = threading.RLock()
        connection.state = "online"
        connection.proc = _Process()
        connection.tools = [{"name": "read_only"}]
        connection.spec = {"name": "test-server"}
        connection.last_execution = None
        connection._request = lambda *args, **kwargs: {
            "content": [{"type": "text", "text": "ok"}]
        }

        with patch(
            "mcp_monitor.time.perf_counter_ns",
            side_effect=[1_000_000, 1_375_000],
        ), patch("mcp_monitor.time.time", return_value=1234.5):
            evidence = connection.call_tool("read_only", {}, timeout=1)

        self.assertEqual(evidence["duration_ms"], 0.375)
        self.assertEqual(evidence["verification"], "not_performed")
        self.assertEqual(evidence["timestamp"], 1234.5)

    def test_failed_tool_request_retains_high_resolution_duration(self):
        connection = MCPConnection.__new__(MCPConnection)
        connection.lock = threading.RLock()
        connection.state = "online"
        connection.proc = _Process()
        connection.tools = [{"name": "read_only"}]
        connection.spec = {"name": "test-server"}
        connection.last_execution = None

        def fail_request(*args, **kwargs):
            raise TimeoutError("simulated timeout")

        connection._request = fail_request
        with patch(
            "mcp_monitor.time.perf_counter_ns",
            side_effect=[2_000_000, 3_625_000],
        ), patch("mcp_monitor.time.time", return_value=1235.0):
            evidence = connection.call_tool("read_only", {}, timeout=1)

        self.assertEqual(evidence["status"], "FAILED")
        self.assertEqual(evidence["verification"], "not_performed")
        self.assertEqual(evidence["duration_ms"], 1.625)
        self.assertIn("simulated timeout", evidence["error"])



    def test_explicit_negative_verification_is_distinct_from_execution_failure(self):
        connection = MCPConnection.__new__(MCPConnection)
        connection.lock = threading.RLock()
        connection.state = "online"
        connection.proc = _Process()
        connection.tools = [{"name": "check"}]
        connection.spec = {"name": "test-server"}
        connection.last_execution = None
        connection._request = lambda *args, **kwargs: {
            "structuredContent": {"verified": False}
        }

        with patch(
            "mcp_monitor.time.perf_counter_ns",
            side_effect=[4_000_000, 5_000_000],
        ), patch("mcp_monitor.time.time", return_value=1236.0):
            evidence = connection.call_tool("check", {}, timeout=1)

        self.assertEqual(evidence["status"], "EXECUTED_UNVERIFIED")
        self.assertEqual(evidence["verification"], "failed")

    def test_tool_execution_error_does_not_claim_verification_was_attempted(self):
        connection = MCPConnection.__new__(MCPConnection)
        connection.lock = threading.RLock()
        connection.state = "online"
        connection.proc = _Process()
        connection.tools = [{"name": "read_only"}]
        connection.spec = {"name": "test-server"}
        connection.last_execution = None
        connection._request = lambda *args, **kwargs: {
            "isError": True,
            "structuredContent": {"verified": True},
        }

        with patch(
            "mcp_monitor.time.perf_counter_ns",
            side_effect=[6_000_000, 7_000_000],
        ), patch("mcp_monitor.time.time", return_value=1237.0):
            evidence = connection.call_tool("read_only", {}, timeout=1)

        self.assertEqual(evidence["status"], "FAILED")
        self.assertEqual(evidence["verification"], "not_performed")


    def test_real_stdio_tool_call_records_nonzero_high_resolution_duration(self):
        with tempfile.TemporaryDirectory(prefix="atlas-mcp-audit-") as folder:
            server_script = pathlib.Path(folder) / "fake_mcp.py"
            server_script.write_text(textwrap.dedent("""
                import json
                import sys
                import time

                for line in sys.stdin:
                    request = json.loads(line)
                    method = request.get("method")
                    request_id = request.get("id")
                    if request_id is None:
                        continue
                    if method == "initialize":
                        result = {"protocolVersion": "2024-11-05", "capabilities": {}}
                    elif method == "tools/list":
                        result = {"tools": [{
                            "name": "delayed_read",
                            "description": "Synthetic timing test",
                            "inputSchema": {"type": "object", "properties": {}},
                        }]}
                    elif method == "tools/call":
                        time.sleep(0.03)
                        result = {
                            "structuredContent": {"verified": True},
                            "content": [{"type": "text", "text": "ok"}],
                        }
                    else:
                        result = {}
                    print(json.dumps({
                        "jsonrpc": "2.0", "id": request_id, "result": result
                    }), flush=True)
            """), encoding="utf-8")

            monitor = MCPMonitor([{
                "name": "synthetic-timing-server",
                "command": [sys.executable, "-S", "-u", str(server_script)],
                "cwd": folder,
                "env": {},
                "handshake_timeout": 5,
            }])
            try:
                status = monitor.check_all()
                self.assertEqual(status["online"], 1)
                evidence = monitor.call_tool(
                    "synthetic-timing-server", "delayed_read", {}, timeout=2
                )
                self.assertEqual(evidence["status"], "VERIFIED")
                self.assertEqual(evidence["verification"], "passed")
                self.assertGreaterEqual(evidence["duration_ms"], 20.0)
                self.assertLess(evidence["duration_ms"], 2000.0)
            finally:
                monitor.stop_all()

if __name__ == "__main__":
    unittest.main()
