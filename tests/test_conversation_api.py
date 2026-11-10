
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer

import _paths  # noqa: F401  (shipped code first on sys.path)
import server
import atlas_observability as ops

class ConversationDiagnosticsApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data = server.DATA
        self.old_db = ops.DB_PATH
        server.DATA = str(Path(self.tmp.name) / "data.json")
        ops.DB_PATH = Path(self.tmp.name) / "observability.sqlite3"
        Path(server.DATA).write_text(json.dumps({
            "bots": [{"id": "bot_1", "name": "Coder", "model": "coder"}],
            "chats": [{"id": "chat_1", "botId": "bot_1", "title": "Queue diagnostics",
                       "messages": [{"role": "user", "content": "hello"}]}]
        }), encoding="utf-8")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server.DATA = self.old_data
        ops.DB_PATH = self.old_db
        self.tmp.cleanup()

    def request(self, path, method="GET", body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())

    def test_task_and_mcp_events_are_returned_for_saved_conversation(self):
        status, task = self.request("/api/ops/tasks", "POST", {
            "type": "coding", "conversation_id": "chat_1", "bot_id": "bot_1",
            "payload": {"prompt": "fix queue"}
        })
        self.assertEqual(status, 202)
        ops.record_local_event("chat_1", "bot_1", "mcp.tool", "filesystem / list: EXECUTED_UNVERIFIED",
                               {"server": "filesystem", "tool": "list"})
        status, diagnostics = self.request("/api/ops/conversations/chat_1")
        self.assertEqual(status, 200)
        self.assertEqual(diagnostics["conversation"]["title"], "Queue diagnostics")
        self.assertEqual(diagnostics["conversation"]["bot_name"], "Coder")
        self.assertEqual(diagnostics["tasks"][0]["task_id"], task["task_id"])
        self.assertEqual(diagnostics["events"][0]["kind"], "task.queued")
        self.assertEqual(diagnostics["events"][1]["kind"], "mcp.tool")
        self.assertEqual(diagnostics["mcp_audit"][0]["kind"], "mcp.tool")

    def test_unknown_conversation_returns_404(self):
        try:
            self.request("/api/ops/conversations/missing")
        except Exception as exc:
            self.assertIn("404", str(exc))
        else:
            self.fail("Unknown conversation should return HTTP 404")


    def test_chat_mcp_proxy_correlates_audit_and_strips_private_metadata(self):
        from http.server import BaseHTTPRequestHandler
        import http.server
        import threading

        upstream_requests = []
        class FakeUpstreamHandler(BaseHTTPRequestHandler):
            call_count = 0
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                upstream_requests.append(json.loads(raw))
                FakeUpstreamHandler.call_count += 1
                if FakeUpstreamHandler.call_count == 1:
                    payload = {"choices": [{"message": {"role": "assistant", "content": None,
                        "tool_calls": [{"id": "call-1", "type": "function",
                            "function": {"name": "safe-files__list_files", "arguments": "{}"}}]},
                        "finish_reason": "tool_calls"}]}
                else:
                    payload = {"choices": [{"message": {"role": "assistant",
                        "content": "Found file-a.py."}, "finish_reason": "stop"}]}
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass

        class FakeMCP:
            def status(self):
                return {"configured": 1, "online": 1, "servers": [{
                    "name": "safe-files", "state": "online",
                    "tools": [{"name": "list_files", "description": "List files",
                               "inputSchema": {"type": "object", "properties": {}}}]
                }]}
            def call_tool(self, server_name, tool_name, arguments, timeout=30):
                return {"server": server_name, "tool": tool_name,
                        "status": "EXECUTED_UNVERIFIED", "verification": "not_performed",
                        "result": {"content": [{"type": "text", "text": "file-a.py"}]}}

        old_mcp = server._MCP
        old_upstream = (server.UPSTREAM_HOST, server.UPSTREAM_PORT)
        upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstreamHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        server.UPSTREAM_HOST, server.UPSTREAM_PORT = "127.0.0.1", upstream.server_port
        server._MCP = FakeMCP()
        try:
            payload = {
                "model": "coder", "stream": True,
                "messages": [{"role": "user", "content": "List files"}],
                "_atlas_context": {"conversation_id": "chat_1", "bot_id": "bot_1",
                                   "request_id": "req_1"}
            }
            req = urllib.request.Request(self.base + "/v1/chat/completions",
                data=json.dumps(payload).encode(), method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as response:
                stream = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn("Found file-a.py.", stream)
        finally:
            server._MCP = old_mcp
            server.UPSTREAM_HOST, server.UPSTREAM_PORT = old_upstream
            upstream.shutdown(); upstream.server_close(); upstream_thread.join(timeout=2)

        self.assertTrue(upstream_requests)
        self.assertTrue(all("_atlas_context" not in request for request in upstream_requests))
        diagnostics = ops.conversation_diagnostics("chat_1")
        kinds = [event["kind"] for event in diagnostics["events"]]
        self.assertIn("chat.request.started", kinds)
        self.assertIn("mcp.tool", kinds)
        self.assertIn("chat.request.completed", kinds)

if __name__ == "__main__":
    unittest.main()


