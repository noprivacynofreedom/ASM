"""Regression tests for persisted MCP server configuration."""
import os
import unittest
import _paths  # noqa: F401  (shipped code first on sys.path)
from mcp_monitor import build_mcp_specs


class MCPConfigTests(unittest.TestCase):
    def test_builds_argv_spec_and_expands_placeholders(self):
        specs = build_mcp_specs([{
            "name": "bridge",
            "enabled": True,
            "command": ["{python}", "{project}/bridge.py", "--stdio"],
            "cwd": "{project}/workspace",
            "env": {"BRIDGE_HOME": "%ATLAS_TEST_HOME%"},
            "handshake_timeout": 37,
        }], r"C:\Atlas", r"C:\Python\python.exe")
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["command"], [
            r"C:\Python\python.exe", r"C:\Atlas/bridge.py", "--stdio"
        ])
        self.assertEqual(specs[0]["cwd"], r"C:\Atlas/workspace")
        self.assertEqual(specs[0]["handshake_timeout"], 37.0)
        self.assertIn("BRIDGE_HOME", specs[0]["env"])

    def test_timeout_is_clamped_and_invalid_timeout_falls_back(self):
        rows = [
            {"name": "low", "command": ["python", "low.py"], "handshake_timeout": 0},
            {"name": "high", "command": ["python", "high.py"], "handshake_timeout": 999},
            {"name": "bad", "command": ["python", "bad.py"], "handshake_timeout": "invalid"},
            {"name": "nan", "command": ["python", "nan.py"], "handshake_timeout": float("nan")},
        ]
        specs = build_mcp_specs(rows, "/project", "python")
        self.assertEqual([x["handshake_timeout"] for x in specs], [1.0, 60.0, 20.0, 20.0])

    def test_disabled_malformed_and_empty_commands_are_ignored(self):
        rows = [
            {"name": "disabled", "enabled": False, "command": ["python", "x.py"]},
            {"name": "string-command", "command": "python x.py"},
            {"name": "empty-command", "command": []},
            None,
            {"name": "valid", "command": ["python", "x.py"]},
        ]
        specs = build_mcp_specs(rows, "/project", "python")
        self.assertEqual([x["name"] for x in specs], ["valid"])


if __name__ == "__main__":
    unittest.main()
