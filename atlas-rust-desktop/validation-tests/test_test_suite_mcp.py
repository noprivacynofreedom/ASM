import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ATLAS = Path(__file__).resolve().parent.parent / "src-tauri" / "resources" / "atlas"
sys.path.insert(0, str(ATLAS))
import mcp_chat  # noqa: E402
import test_suite_mcp  # noqa: E402


class TestSuiteTiers(unittest.TestCase):
    def test_tiers_cover_all_tools(self):
        names = {t[0] for t in test_suite_mcp.TOOLS}
        self.assertEqual(names, {"test_suite_list", "test_suite_add", "test_suite_update", "test_suite_log_run"})
        self.assertEqual(mcp_chat.TOOL_TIERS["test_suite_list"], "read")
        for n in ("test_suite_add", "test_suite_update", "test_suite_log_run"):
            self.assertEqual(mcp_chat.TOOL_TIERS[n], "write")

    def test_patch_dict_tool_tiers_helper(self):
        with patch.dict(mcp_chat.TOOL_TIERS, {"test_suite_list": "read", "custom_probe": "read"}):
            self.assertEqual(mcp_chat.tool_tier("test_suite_list"), "read")
            self.assertEqual(mcp_chat.tool_tier("custom_probe"), "read")


class TestSuiteStoreAndTools(unittest.TestCase):
    def test_add_update_list_log_run_never_touches_data_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            sentinel = data_dir / "data.json"
            sentinel.write_text('{"chats": ["keep"]}', encoding="utf-8")

            feat = test_suite_mcp.add_feature(
                data_dir,
                title="Kanban tickbox persistence",
                description="Ensure tickboxes persist",
                status="queued",
                ticks=["Create feature", "Toggle tickbox"],
                feedback="Initial model note",
                author="model-a",
            )
            fid = feat["id"]
            self.assertEqual(feat["status"], "queued")
            self.assertEqual(len(feat["ticks"]), 2)
            tick0 = feat["ticks"][0]["id"]

            updated = test_suite_mcp.update_feature(
                data_dir,
                feature_id=fid,
                status="testing",
                toggle_tick=tick0,
                add_tick="Verify Needs Fix column",
                feedback="Checked first tickbox",
                author="model-b",
            )
            self.assertEqual(updated["status"], "testing")
            self.assertTrue(updated["ticks"][0]["done"])
            self.assertFalse(updated["ticks"][1]["done"])
            self.assertEqual(len(updated["ticks"]), 3)
            self.assertEqual(len(updated["feedback"]), 2)

            run = test_suite_mcp.log_run(
                data_dir,
                label="build-2026-11-18",
                summary="All checks passed",
                kind="test_pass",
                feature_feedback=[{"feature_id": fid, "status": "passed", "note": "Verified end-to-end"}],
            )
            self.assertEqual(run["label"], "build-2026-11-18")

            listed = test_suite_mcp.list_suite(data_dir, status="passed")
            self.assertEqual(listed["counts"]["passed"], 1)
            self.assertEqual(len(listed["features"]), 1)
            self.assertEqual(listed["features"][0]["feedback"][-1]["note"], "Verified end-to-end")
            self.assertEqual(len(listed["runs"]), 1)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), '{"chats": ["keep"]}')


class TestSuiteProtocol(unittest.TestCase):
    def test_handle_and_stdio_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = test_suite_mcp.TestSuiteMCP(tmp)
            self.assertIsNone(test_suite_mcp.handle(suite, {"method": "notifications/initialized"}))
            init = test_suite_mcp.handle(suite, {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
            self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")
            listed = test_suite_mcp.handle(suite, {"id": 2, "method": "tools/list"})
            self.assertEqual(len(listed["result"]["tools"]), 4)
            bad = test_suite_mcp.handle(suite, {"id": 3, "method": "tools/call", "params": {"name": "nope"}})
            self.assertEqual(bad["error"]["code"], -32602)

            inp = "\n".join(
                json.dumps(m)
                for m in (
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "test_suite_add", "arguments": {"title": "Subprocess card", "ticks": ["Step 1"]}}},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "test_suite_list", "arguments": {}}},
                )
            ) + "\n"
            env = dict(os.environ, ATLAS_DATA_DIR=tmp)
            proc = subprocess.run(
                [sys.executable, str(ATLAS / "test_suite_mcp.py")],
                input=inp,
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            lines = [json.loads(line) for line in proc.stdout.strip().splitlines()]
            self.assertEqual(len(lines), 3)
            list_payload = json.loads(lines[2]["result"]["content"][0]["text"])
            self.assertEqual(len(list_payload["features"]), 1)
            self.assertEqual(list_payload["features"][0]["title"], "Subprocess card")


class TestSuiteServerRoutes(unittest.TestCase):
    @staticmethod
    def _call_handler(handler_cls, method, path, body=None, headers=None):
        h = handler_cls.__new__(handler_cls)
        h.path = path
        h.client_address = ("127.0.0.1", 12345)
        raw = body.encode("utf-8") if isinstance(body, str) else (body or b"")
        hdrs = dict(headers or {})
        if raw and "Content-Length" not in hdrs:
            hdrs["Content-Length"] = str(len(raw))
        h.headers = hdrs
        h.rfile = io.BytesIO(raw)
        sent = {}

        def _send(code, payload, ctype="application/json"):
            sent["code"] = code
            sent["body"] = payload
            sent["ctype"] = ctype

        h._send = _send
        if method == "GET":
            h.do_GET()
        else:
            h.do_POST()
        return sent

    def test_http_get_and_post_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_env = os.environ.get("ATLAS_DATA_DIR")
            os.environ["ATLAS_DATA_DIR"] = tmp
            try:
                import server  # noqa: E402
                with patch.object(server, "DATA_DIR", tmp):
                    r_html = self._call_handler(server.Handler, "GET", "/test-suite")
                    self.assertEqual(r_html["code"], 200)
                    html_body = r_html["body"].decode("utf-8")
                    self.assertIn("Atlas Test Suite", html_body)
                    self.assertIn("atlasUiTheme", html_body)

                    r_add = self._call_handler(
                        server.Handler,
                        "POST",
                        "/api/test-suite",
                        body=json.dumps({"action": "add", "title": "HTTP card", "ticks": ["Check 1"]}),
                        headers={"Content-Type": "application/json"},
                    )
                    self.assertEqual(r_add["code"], 200)
                    add_data = json.loads(r_add["body"])
                    self.assertTrue(add_data["ok"])
                    fid = add_data["feature"]["id"]

                    r_get = self._call_handler(server.Handler, "GET", "/api/test-suite")
                    self.assertEqual(r_get["code"], 200)
                    get_data = json.loads(r_get["body"])
                    self.assertEqual(get_data["counts"]["queued"], 1)

                    r_upd = self._call_handler(
                        server.Handler,
                        "POST",
                        "/api/test-suite",
                        body=json.dumps({"action": "update", "feature_id": fid, "status": "passed", "feedback": "Looks good"}),
                        headers={"Content-Type": "application/json"},
                    )
                    self.assertEqual(r_upd["code"], 200)
                    upd_data = json.loads(r_upd["body"])
                    self.assertEqual(upd_data["feature"]["status"], "passed")
            finally:
                if old_env is None:
                    os.environ.pop("ATLAS_DATA_DIR", None)
                else:
                    os.environ["ATLAS_DATA_DIR"] = old_env


if __name__ == "__main__":
    unittest.main()
