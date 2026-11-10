"""MCP end-to-end smoke tests for Atlas' stdio host and Commander server."""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import _paths
ROOT = _paths.APP
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_monitor import MCPConnection, MCPMonitor


class MCPStdioIntegrationTests(unittest.TestCase):
    def test_initialize_discovery_execution_verification_and_path_containment(self):
        with tempfile.TemporaryDirectory(prefix="atlas-mcp-test-") as folder:
            workspace = pathlib.Path(folder)
            proof = workspace / "proof.txt"
            proof.write_text("atlas mcp integration test", encoding="utf-8")
            outside = pathlib.Path(folder).parent / (workspace.name + "-outside.txt")
            outside.write_text("must not be readable", encoding="utf-8")
            old_workspace = os.environ.get("ATLAS_WORKSPACE")
            os.environ["ATLAS_WORKSPACE"] = str(workspace)
            spec = {
                "name": "atlas-commander-test",
                "command": [sys.executable, "-u", str(ROOT / "src" / "mcp_commander.py")],
                "cwd": str(ROOT),
                "handshake_timeout": 20,
            }
            monitor = MCPMonitor([spec])
            try:
                status = monitor.check_all()
                self.assertEqual(status["online"], 1, json.dumps(status, indent=2))
                server = status["servers"][0]
                names = {tool["name"] for tool in server["tools"]}
                self.assertIn("list_workspace_files", names)
                self.assertIn("verify_workspace_file", names)

                listed = monitor.call_tool("atlas-commander-test", "list_workspace_files", {"path": "."})
                self.assertEqual(listed["status"], "EXECUTED_UNVERIFIED")
                self.assertIn("proof.txt", json.dumps(listed["result"]))

                verified = monitor.call_tool("atlas-commander-test", "verify_workspace_file", {"path": "proof.txt"})
                self.assertEqual(verified["status"], "VERIFIED")
                self.assertTrue(verified["result"]["structuredContent"]["verified"])

                rejected = monitor.call_tool(
                    "atlas-commander-test", "read_workspace_file", {"path": "../" + outside.name}
                )
                self.assertEqual(rejected["status"], "FAILED")
                self.assertIn("outside", json.dumps(rejected["result"]).lower())
            finally:
                monitor.stop_all()
                if old_workspace is None:
                    os.environ.pop("ATLAS_WORKSPACE", None)
                else:
                    os.environ["ATLAS_WORKSPACE"] = old_workspace
                outside.unlink(missing_ok=True)

    def test_unknown_server_and_unadvertised_tool_are_rejected(self):
        monitor = MCPMonitor([])
        with self.assertRaises(KeyError):
            monitor.call_tool("missing", "anything", {})

    def test_failed_handshake_terminates_owned_mcp_child(self):
        connection = MCPConnection({
            "name": "broken-server",
            "command": [sys.executable, "-c", "pass"],
            "handshake_timeout": 1,
        })
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = [
            __import__("subprocess").TimeoutExpired("broken-server", 1.5),
            0,
        ]
        connection.proc = child
        with patch.object(connection, "_start"), patch.object(connection, "_request", side_effect=TimeoutError("initialize timed out")):
            result = connection.connect_and_check()
        self.assertEqual(result["state"], "error")
        self.assertFalse(result["process_running"])
        self.assertIn("timed out", result["error"])
        child.terminate.assert_called_once_with()
        self.assertEqual(child.wait.call_count, 2)
        child.wait.assert_any_call(timeout=1.5)
        child.wait.assert_any_call(timeout=3)


if __name__ == "__main__":
    unittest.main()
