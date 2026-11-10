"""Atlas Commander: path handling and MCP error shape (runs the real server over stdio)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

COMMANDER = Path(__file__).resolve().parents[1] / "atlas-rust-desktop" / "src-tauri" / "resources" / "atlas" / "src" / "mcp_commander.py"


def call(root, name, arguments):
    env = {"ATLAS_WORKSPACE": str(root), "SYSTEMROOT": "C:\\Windows"}
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
    ]
    done = subprocess.run([sys.executable, "-I", str(COMMANDER)], input="\n".join(map(json.dumps, requests)) + "\n",
                          capture_output=True, text=True, env=env, timeout=30)
    return json.loads(done.stdout.strip().splitlines()[-1])


class CommanderPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "sub").mkdir()
        (self.root / "sub" / "a.txt").write_text("hello", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_relative_read(self):
        result = call(self.root, "read_workspace_file", {"path": "sub/a.txt"})["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["content"], "hello")

    def test_backslash_and_alias_argument(self):
        result = call(self.root, "atlas_read_file", {"relative_path": "sub\\a.txt"})["result"]
        self.assertFalse(result["isError"])

    def test_absolute_path_inside_root_is_accepted(self):
        result = call(self.root, "read_workspace_file", {"path": str(self.root / "sub" / "a.txt")})["result"]
        self.assertFalse(result["isError"])

    def test_outside_root_is_a_tool_error_not_a_protocol_error(self):
        response = call(self.root, "read_workspace_file", {"path": "../escape.txt"})
        self.assertNotIn("error", response)
        self.assertTrue(response["result"]["isError"])
        self.assertIn("outside", response["result"]["content"][0]["text"].lower())

    def test_wrapped_path_argument_is_unwrapped(self):
        # Local models send {"path": {"path": "a.txt"}} or {"path": ["a.txt"]}; that used to become the text "{'path': 'a.txt'}".
        for arg in ({"path": "sub/a.txt"}, ["sub/a.txt"]):
            result = call(self.root, "read_workspace_file", {"path": arg})["result"]
            self.assertFalse(result["isError"], arg)
            self.assertEqual(result["structuredContent"]["content"], "hello")

    def test_wrapped_folder_is_listed(self):
        result = call(self.root, "list_workspace_files", {"path": {"path": "sub"}})["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["path"], "sub")
        self.assertEqual([e["name"] for e in result["structuredContent"]["entries"]], ["a.txt"])

    def test_wrapped_path_cannot_escape_the_root(self):
        result = call(self.root, "read_workspace_file", {"path": {"path": "../escape.txt"}})["result"]
        self.assertTrue(result["isError"])
        self.assertIn("outside", result["content"][0]["text"].lower())

    def test_missing_file_is_a_tool_error(self):
        response = call(self.root, "read_workspace_file", {"path": "nope.txt"})
        self.assertTrue(response["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
