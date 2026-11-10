"""Regression tests for the MCP / request-handling fixes (branch fix/mcp-request-hardening).

One class per area. Each test names the bug it pins down.
"""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Self-contained on purpose: put the SHIPPED backend (what the installer bundles) first on sys.path.
APP = Path(__file__).resolve().parents[1] / "atlas-rust-desktop" / "src-tauri" / "resources" / "atlas"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import mcp_chat  # noqa: E402
import mcp_monitor  # noqa: E402
import server  # noqa: E402

COMMANDER = APP / "src" / "mcp_commander.py"


def rpc(root, messages, env_extra=None, isolated=True):
    """Run the real commander over stdio and return the list of JSON replies."""
    env = {"ATLAS_WORKSPACE": str(root), "SYSTEMROOT": "C:\\Windows", "PATH": os.environ.get("PATH", "")}
    env.update(env_extra or {})
    cmd = [sys.executable] + (["-I"] if isolated else []) + [str(COMMANDER)]
    done = subprocess.run(cmd, input="\n".join(map(json.dumps, messages)) + "\n",
                          capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


def tool(root, name, arguments, **kw):
    replies = rpc(root, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": arguments}}], **kw)
    return replies[-1]["result"]


class CommanderHardening(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("[remote]\nurl = https://user:TOKEN@example.com/r.git\n")
        (self.root / ".env").write_text("SECRET=1\n")
        (self.root / "ok.txt").write_text("fine", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_git_internals_and_env_files_cannot_be_read(self):
        # Bug: EXCLUDED only hid .git from listings; read_workspace_file would return .git/config (URL tokens).
        for path in (".git/config", ".env"):
            result = tool(self.root, "read_workspace_file", {"path": path})
            self.assertTrue(result["isError"], path)
            self.assertIn("protected", result["content"][0]["text"])
            self.assertTrue(tool(self.root, "verify_workspace_file", {"path": path})["isError"], path)

    def test_credentials_inside_settings_json_are_masked(self):
        # Bug: settings.json holds upstream_api_key and the model could read it in clear text.
        (self.root / "settings.json").write_text(json.dumps(
            {"upstream_api_key": "sk-live-123", "server_port": 8090, "mcp_servers": [{"env": {"API_TOKEN": "t0k"}}]}))
        text = tool(self.root, "read_workspace_file", {"path": "settings.json"})["structuredContent"]["content"]
        self.assertNotIn("sk-live-123", text)
        self.assertNotIn("t0k", text)
        self.assertIn("8090", text)

    def test_listing_hides_secret_files(self):
        names = [e["name"] for e in tool(self.root, "list_workspace_files", {})["structuredContent"]["entries"]]
        self.assertIn("ok.txt", names)
        self.assertNotIn(".env", names)
        self.assertNotIn(".git", names)

    def test_oversized_file_is_refused_by_size_check(self):
        (self.root / "big.txt").write_bytes(b"a" * 300000)
        result = tool(self.root, "read_workspace_file", {"path": "big.txt"})
        self.assertTrue(result["isError"])
        self.assertIn("read limit", result["content"][0]["text"])

    def test_binary_file_is_refused(self):
        (self.root / "x.bin").write_bytes(b"\x89PNG\x00\x00\x01binary")
        result = tool(self.root, "read_workspace_file", {"path": "x.bin"})
        self.assertTrue(result["isError"])
        self.assertIn("binary", result["content"][0]["text"])

    def test_listing_says_when_it_was_cut(self):
        for i in range(210):
            (self.root / f"f{i:03}.txt").write_text("x")
        out = tool(self.root, "list_workspace_files", {})["structuredContent"]
        self.assertEqual(len(out["entries"]), 200)
        self.assertTrue(out["truncated"])

    def test_notification_without_id_gets_no_reply(self):
        # Bug: any id-less message other than notifications/* was answered with "id": null.
        replies = rpc(self.root, [{"jsonrpc": "2.0", "method": "ping"},
                                  {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                  {"jsonrpc": "2.0", "id": 7, "method": "ping"}])
        self.assertEqual([r["id"] for r in replies], [7])

    def test_tools_call_params_must_be_an_object(self):
        replies = rpc(self.root, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": ["x"]}])
        self.assertEqual(replies[0]["error"]["code"], -32602)

    def test_initialize_echoes_a_supported_protocol_version(self):
        replies = rpc(self.root, [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": "2025-03-26"}},
                                  {"jsonrpc": "2.0", "id": 2, "method": "initialize",
                                   "params": {"protocolVersion": "1999-01-01"}}])
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(replies[1]["result"]["protocolVersion"], "2024-11-05")

    def test_non_ascii_content_survives_a_narrow_default_encoding(self):
        # Bug: on Windows stdio defaults to cp1252; non-ASCII file content broke the reply.
        (self.root / "u.txt").write_text("caf\u00e9 \u2713 \u65e5\u672c", encoding="utf-8")
        result = tool(self.root, "read_workspace_file", {"path": "u.txt"},
                      env_extra={"PYTHONIOENCODING": "ascii"}, isolated=False)
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["content"], "caf\u00e9 \u2713 \u65e5\u672c")


FAKE_MCP = textwrap.dedent('''
    import json, sys
    inits = 0
    for line in sys.stdin:
        m = json.loads(line)
        method, rid = m.get("method"), m.get("id")
        if rid is None:
            continue
        if method == "initialize":
            inits += 1
            if inits > 1:  # a strict server: initialize twice is an error
                out = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32600, "message": "already initialized"}}
            else:
                print("123", flush=True)      # junk: valid JSON but not a JSON-RPC object
                print("[1, 2]", flush=True)
                out = {"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2024-11-05",
                       "capabilities": {}, "serverInfo": {"name": "fake", "version": "1"}}}
        elif method == "tools/list":
            if not (m.get("params") or {}).get("cursor"):
                tools, nxt = [{"name": "a"}, {"name": "b", "inputSchema": {"type": "object"}}, "junk"], "page2"
            else:
                tools, nxt = [{"name": "c", "description": "third"}], None
            result = {"tools": tools}
            if nxt:
                result["nextCursor"] = nxt
            out = {"jsonrpc": "2.0", "id": rid, "result": result}
        elif method == "tools/call":
            out = {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": "ran"}], "isError": False}}
        else:
            out = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "nope"}}
        print(json.dumps(out), flush=True)
''')


class MonitorHardening(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        script = Path(self.tmp.name) / "fake_mcp.py"
        script.write_text(FAKE_MCP, encoding="utf-8")
        self.spec = {"name": "fake", "command": [sys.executable, "-u", str(script)], "cwd": self.tmp.name,
                     "env": {}, "handshake_timeout": 10.0}
        self.conn = mcp_monitor.MCPConnection(self.spec)

    def tearDown(self):
        self.conn.stop()
        self.tmp.cleanup()

    def test_all_tool_pages_are_read_and_junk_entries_dropped(self):
        # Bug: only the first tools/list page was read; a non-dict entry crashed the handshake.
        snap = self.conn.connect_and_check()
        self.assertEqual(snap["state"], "online", snap["error"])
        self.assertEqual([t["name"] for t in snap["tools"]], ["a", "b", "c"])

    def test_non_object_stdout_lines_do_not_kill_the_reader(self):
        # Bug: a line like `123` raised in the reader thread; every later call then timed out.
        self.assertEqual(self.conn.connect_and_check()["state"], "online")
        evidence = self.conn.call_tool("a", {}, timeout=5)
        self.assertEqual(evidence["status"], "EXECUTED_UNVERIFIED", evidence)

    def test_second_check_does_not_reinitialize_a_healthy_server(self):
        # Bug: every status check re-sent `initialize`; a strict server errored and was then killed.
        self.assertEqual(self.conn.connect_and_check()["state"], "online")
        pid = self.conn.proc.pid
        again = self.conn.connect_and_check()
        self.assertEqual(again["state"], "online", again["error"])
        self.assertEqual(self.conn.proc.pid, pid)

    def test_duplicate_server_names_are_kept_apart(self):
        row = {"name": "same", "command": ["x"]}
        specs = mcp_monitor.build_mcp_specs([row, dict(row), dict(row)], "/p", "py")
        self.assertEqual([s["name"] for s in specs], ["same", "same-2", "same-3"])

    def test_ensure_online_does_not_retry_a_broken_server_every_time(self):
        # Bug: a server that cannot start was re-tried on every chat request.
        bad = {"name": "bad", "command": ["/definitely/not/a/program"], "cwd": self.tmp.name, "env": {},
               "handshake_timeout": 2.0}
        monitor = mcp_monitor.MCPMonitor([bad])
        monitor.ensure_online(30.0)
        first = monitor.connections["bad"].last_check
        self.assertIsNotNone(first)
        time.sleep(0.05)
        monitor.ensure_online(30.0)
        self.assertEqual(monitor.connections["bad"].last_check, first)  # not retried inside the interval
        monitor.ensure_online(0.0)
        self.assertGreater(monitor.connections["bad"].last_check, first)  # retried once the interval passed


class FakeMonitor:
    def __init__(self, tools):
        self.tools, self.calls = tools, []

    def status(self):
        return {"servers": [{"name": "s", "state": "online", "tools": self.tools}]}

    def call_tool(self, server_name, tool_name, arguments=None, timeout=30):
        self.calls.append((tool_name, arguments))
        return {"status": "EXECUTED_UNVERIFIED", "result": {"content": [{"type": "text", "text": "ok"}]}}


class ToolLoopHardening(unittest.TestCase):
    def test_no_tools_raises_the_dedicated_error(self):
        with self.assertRaises(mcp_chat.NoLiveTools):
            mcp_chat.run_tool_loop({"messages": [{"role": "user", "content": "hi"}]}, FakeMonitor([]),
                                   lambda e: e, "127.0.0.1", 1)

    def test_null_arguments_run_a_parameterless_tool(self):
        # Bug: "arguments": null was rejected as invalid, so tools without parameters failed.
        monitor = FakeMonitor([{"name": "status", "description": "", "inputSchema": {"type": "object"}}])
        replies = [
            {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "s__status", "arguments": None}}]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}]},
        ]
        original = mcp_chat._post_completion
        mcp_chat._post_completion = lambda host, port, request: replies.pop(0)
        try:
            completion, events = mcp_chat.run_tool_loop({"messages": [{"role": "user", "content": "go"}]},
                                                        monitor, lambda e: e, "h", 1)
        finally:
            mcp_chat._post_completion = original
        self.assertEqual(monitor.calls, [("status", {})])
        self.assertEqual(completion["choices"][0]["message"]["content"], "done")


class FakeUpstream(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        FakeUpstream.seen.append(json.loads(body))
        data = json.dumps({"choices": [{"message": {"role": "assistant", "content": "plain upstream answer"},
                                        "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ServerHardening(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (server.BOTS_DIR, server.UPSTREAM_HOST, server.UPSTREAM_PORT, server._MCP,
                      server._library_books, server.DATA)
        server.BOTS_DIR = str(Path(self.tmp.name) / "bots")
        server.DATA = str(Path(self.tmp.name) / "data.json")
        server._library_books = lambda: []
        FakeUpstream.seen = []
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
        server.UPSTREAM_HOST, server.UPSTREAM_PORT = "127.0.0.1", self.upstream.server_port
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (self.upstream, self.httpd)]
        for t in self.threads:
            t.start()

    def tearDown(self):
        for s in (self.httpd, self.upstream):
            s.shutdown()
            s.server_close()
        (server.BOTS_DIR, server.UPSTREAM_HOST, server.UPSTREAM_PORT, server._MCP,
         server._library_books, server.DATA) = self.saved
        self.tmp.cleanup()

    def call(self, method, path, body=None, headers=None, raw_headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=10)
        try:
            if raw_headers is not None:
                conn.putrequest(method, path)
                for k, v in raw_headers.items():
                    conn.putheader(k, v)
                conn.endheaders()
            else:
                data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
                conn.request(method, path, body=data, headers=headers or {"Content-Type": "application/json"})
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, raw
        finally:
            conn.close()

    # --- bot workspace files -------------------------------------------------------------------
    def test_bot_files_write_list_read_round_trip(self):
        # Bug: the route check read parts[2] ("<bot_id>") as "files", so GET and POST always returned 404.
        code, raw = self.call("POST", "/api/bot/bot_1/files", {"name": "notes.txt", "content": "hello"})
        self.assertEqual(code, 200, raw)
        code, raw = self.call("GET", "/api/bot/bot_1/files")
        self.assertEqual((code, json.loads(raw)["files"]), (200, ["notes.txt"]))
        code, raw = self.call("GET", "/api/bot/bot_1/files/notes.txt")
        self.assertEqual((code, json.loads(raw)["content"]), (200, "hello"))

    def test_bot_files_reject_bad_input_with_4xx_not_500(self):
        for name in ("..", ".", "a/b", "a\\b", "c:evil", "x\x00y", ""):
            code, _ = self.call("POST", "/api/bot/bot_1/files", {"name": name, "content": "x"})
            self.assertEqual(code, 400, repr(name))
        self.assertEqual(self.call("POST", "/api/bot/bot_1/files", {"name": "a", "content": 5})[0], 400)
        self.assertEqual(self.call("POST", "/api/bot/bot_1/files", [1, 2])[0], 400)
        self.assertEqual(self.call("POST", "/api/bot/bot_1/files", b"{not json")[0], 400)
        self.assertEqual(self.call("POST", "/api/bot/bad%20id!/files", {"name": "a", "content": "x"})[0], 400)
        self.assertEqual(self.call("GET", "/api/bot/bot_1/files/..%2F..%2Fsecret")[0], 400)

    # --- request bodies ------------------------------------------------------------------------
    def test_bad_content_length_gets_a_400(self):
        # Bug: int("abc") raised outside any handler and the connection was dropped.
        code, raw = self.call("POST", "/api/state", raw_headers={"Content-Length": "abc"})
        self.assertEqual(code, 400, raw)
        self.assertIn("Content-Length", json.loads(raw)["error"])

    def test_oversized_body_gets_a_413_without_reading_it(self):
        code, _ = self.call("POST", "/api/state", raw_headers={"Content-Length": str(10 * 1024 ** 3)})
        self.assertEqual(code, 413)

    # --- system message helper -----------------------------------------------------------------
    def test_append_system_text_handles_list_content(self):
        # Bug: `list + str` raised TypeError for multimodal system content (docs_folder / retrieval).
        msgs = [{"role": "system", "content": [{"type": "text", "text": "A"}]}, {"role": "user", "content": "q"}]
        server._append_system_text(msgs, "B")
        self.assertEqual(msgs[0]["content"], [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}])
        plain = [{"role": "user", "content": "q"}]
        server._append_system_text(plain, "B")
        self.assertEqual(plain[0], {"role": "system", "content": "B"})
        s = [{"role": "system", "content": "A"}]
        server._append_system_text(s, "B")
        self.assertEqual(s[0]["content"], "A\n\nB")

    # --- chat proxy ----------------------------------------------------------------------------
    def test_chat_falls_back_to_plain_upstream_when_mcp_has_no_usable_tools(self):
        # Bug: an online server with zero tools made run_tool_loop raise, and the chat failed with a 502.
        server._MCP = FakeMonitor([])
        server._MCP.ensure_online = lambda interval=30.0: server._MCP.status() | {"configured": 1, "online": 1}
        server._MCP.status = lambda: {"configured": 1, "online": 1, "servers": [{"name": "s", "state": "online", "tools": []}]}
        code, raw = self.call("POST", "/v1/chat/completions",
                              {"model": "m", "stream": False, "messages": [{"role": "user", "content": "hello"}]})
        self.assertEqual(code, 200, raw)
        self.assertEqual(json.loads(raw)["choices"][0]["message"]["content"], "plain upstream answer")
        self.assertEqual(len(FakeUpstream.seen), 1)

    def test_swarm_command_with_leading_whitespace_keeps_the_whole_goal(self):
        # Bug: latest[6:] was taken from the unstripped text, so "  /swarm fix it" lost its first letters.
        server._MCP = FakeMonitor([])
        server._MCP.status = lambda: {"configured": 0, "online": 0, "servers": []}
        code, raw = self.call("POST", "/v1/chat/completions",
                              {"model": "m", "messages": [{"role": "user", "content": "  /swarm fix the bug, add a test"}]})
        self.assertEqual(code, 200)
        text = raw.decode()
        self.assertIn("SWARM BREAKDOWN: fix the bug, add a test", text)
        self.assertIn("10x: SDE", text)
        self.assertIn("10x: QA Engineer", text)  # "test," matched despite the comma


if __name__ == "__main__":
    unittest.main()
