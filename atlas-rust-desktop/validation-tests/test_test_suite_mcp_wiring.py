"""The Test Suite / bug tiles are now exposed to agents as a built-in MCP server (test_suite_mcp.py),
and still drive the in-app Kanban. Before this, the Kanban existed but no MCP server registered its tools."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from test_browser_wiring import ATLAS, server_probe

sys.path.insert(0, str(ATLAS))
import mcp_chat  # noqa: E402


class Wiring(unittest.TestCase):
    def test_registered_by_default(self):
        specs = server_probe("print(json.dumps(server._mcp_specs()))")
        ts = [s for s in specs if s["name"] == "test_suite"]
        self.assertEqual(len(ts), 1)
        self.assertTrue(Path(ts[0]["command"][-1]).name == "test_suite_mcp.py")
        self.assertTrue(Path(ts[0]["command"][-1]).is_file())

    def test_off_when_disabled_and_user_entry_wins(self):
        names = server_probe("print(json.dumps([s['name'] for s in server._mcp_specs()]))", {"test_suite_enabled": False})
        self.assertNotIn("test_suite", names)
        own = {"name": "test_suite", "command": ["{python}", "mine.py"]}
        specs = server_probe("print(json.dumps(server._mcp_specs()))", {"mcp_servers": [own]})
        self.assertEqual([s["command"][-1] for s in specs if s["name"] == "test_suite"][0][-7:], "mine.py")

    def test_tiers_read_and_write(self):
        self.assertEqual(mcp_chat.tool_tier("test_suite_list"), "read")
        for w in ("test_suite_add", "test_suite_update", "test_suite_log_run"):
            self.assertEqual(mcp_chat.tool_tier(w), "write", w)

    def test_stdio_server_lists_tools(self):
        reqs = "\n".join(json.dumps(r) for r in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]) + "\n"
        out = subprocess.run([sys.executable, str(ATLAS / "test_suite_mcp.py")], input=reqs,
                             capture_output=True, text=True, env={**os.environ}, timeout=30)
        rows = {json.loads(l)["id"]: json.loads(l) for l in out.stdout.splitlines()}
        names = {t["name"] for t in rows[2]["result"]["tools"]}
        self.assertEqual(names, {"test_suite_list", "test_suite_add", "test_suite_update", "test_suite_log_run"})


class UiHasTiles(unittest.TestCase):
    def test_tiles_view_present(self):
        html = (ATLAS / "test_suite.html").read_text(encoding="utf-8")
        for s in ('id="viewToggleBtn"', 'id="tiles"', 'id="tileGrid"', 'id="tileAddForm"', "function renderTiles(", "NEXT_STATE"):
            self.assertIn(s, html)


if __name__ == "__main__":
    unittest.main()
