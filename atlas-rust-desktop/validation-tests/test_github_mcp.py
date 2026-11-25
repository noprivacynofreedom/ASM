"""Built-in GitHub MCP tools: github_mcp.py over stdio against a fake GitHub API, the approval tiers,
the server.py wiring (off by default, /api/github), the UI control and the installer bundle.
No real GitHub call and no real token."""
import base64
import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from test_browser_wiring import ATLAS, HTML, ROOT, server_probe

sys.path.insert(0, str(ATLAS))
import github_mcp  # noqa: E402
import mcp_chat  # noqa: E402


class FakeGitHub(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        FakeGitHub.calls.append((self.command, self.path, body, self.headers.get("Authorization")))
        p = unquote(self.path.split("?")[0])
        if p == "/repos/me/app/issues" and self.command == "GET":
            return self._reply(200, [{"number": 1, "state": "open", "title": "Bug", "user": {"login": "me"}},
                                     {"number": 2, "state": "open", "title": "A PR", "user": {"login": "me"}, "pull_request": {}}])
        if p == "/repos/me/app/issues" and self.command == "POST":
            return self._reply(201, {"number": 7, "html_url": "https://github.com/me/app/issues/7"})
        if p == "/repos/me/app/contents/docs/a b.md":
            return self._reply(200, {"path": "docs/a b.md", "sha": "abc123", "content": base64.b64encode(b"hello").decode()})
        if p == "/repos/me/app/pulls/9":
            return self._reply(404, {"message": "Not Found"})
        return self._reply(500, {"message": "unexpected " + self.command + " " + p})

    do_GET = do_POST = do_PUT = _handle


def mcp(requests, env_extra):
    lines = "\n".join(json.dumps(r) for r in requests) + "\n"
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    env.update(env_extra)
    out = subprocess.run([sys.executable, str(ATLAS / "github_mcp.py")], input=lines, capture_output=True,
                         text=True, env=env, timeout=60)
    return {r["id"]: r for r in map(json.loads, out.stdout.splitlines())}


def call(i, name, args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}


def text(resp):
    return resp["result"]["content"][0]["text"]


class StdioServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.env = {"ATLAS_GITHUB_API": f"http://127.0.0.1:{cls.httpd.server_port}", "GITHUB_TOKEN": "test-token"}

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        FakeGitHub.calls.clear()

    def test_list_tools_and_read_calls(self):
        r = mcp([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                 call(3, "github_list_issues", {"repo": "me/app"}),
                 call(4, "github_get_file", {"repo": "me/app", "path": "docs/a b.md"})], self.env)
        self.assertEqual(r[1]["result"]["serverInfo"]["name"], "atlas-github")
        self.assertEqual({t["name"] for t in r[2]["result"]["tools"]}, set(github_mcp._FN))
        self.assertIn("#1 [open] Bug", text(r[3]))
        self.assertNotIn("A PR", text(r[3]))  # the issues endpoint also returns PRs; they are filtered out
        self.assertIn("sha abc123", text(r[4]))
        self.assertIn("hello", text(r[4]))
        self.assertTrue(all(c[3] == "Bearer test-token" for c in FakeGitHub.calls))

    def test_write_sends_the_right_body_and_errors_are_tool_errors(self):
        r = mcp([call(1, "github_create_issue", {"repo": "me/app", "title": "New", "body": "Text"}),
                 call(2, "github_get_pr", {"repo": "me/app", "number": 9}),
                 call(3, "github_list_issues", {"repo": "../etc"}),
                 call(4, "nope", {}),
                 call(5, "github_get_file", {"repo": "me/app", "path": "docs/../../../user"}),
                 call(6, "github_list_repos", {"owner": "x/../../admin"})], self.env)
        self.assertIn("no '.' or '..' parts", text(r[5]))
        self.assertTrue(any(c[1].startswith("/users/x%2F..%2F..%2Fadmin/") for c in FakeGitHub.calls))
        self.assertIn("Created issue #7", text(r[1]))
        self.assertIn(("POST", "/repos/me/app/issues", {"title": "New", "body": "Text"}, "Bearer test-token"), FakeGitHub.calls)
        self.assertTrue(r[2]["result"]["isError"])
        self.assertIn("GitHub 404: Not Found", text(r[2]))
        self.assertIn('owner/name', text(r[3]))  # bad repo never reaches the API
        self.assertEqual(r[4]["error"]["code"], -32602)
        self.assertFalse(any("etc" in c[1] for c in FakeGitHub.calls))

    def test_no_token_gives_a_clear_error_and_never_leaks_one(self):
        r = mcp([call(1, "github_list_repos", {})], {**self.env, "GITHUB_TOKEN": "", "PATH": ""})  # no gh on PATH
        self.assertIn("No GitHub token", text(r[1]))
        r = mcp([call(1, "github_create_issue", {"repo": "me/app", "title": "x"})], self.env)
        self.assertNotIn("test-token", json.dumps(r))


class Tiers(unittest.TestCase):
    def test_reads_run_freely_and_writes_always_ask(self):
        for name in github_mcp._FN:
            want = "read" if name.startswith(("github_list_", "github_get_")) else "consequential"
            self.assertEqual(mcp_chat.tool_tier(name), want, name)


class Wiring(unittest.TestCase):
    def test_off_by_default(self):
        names = server_probe("print(json.dumps([s['name'] for s in server._mcp_specs()]))")
        self.assertNotIn("github", names)
        self.assertIn("browser", names)

    def test_on_registers_it_and_user_entry_wins(self):
        specs = server_probe("print(json.dumps(server._mcp_specs()))", {"github_enabled": True})
        gh = [s for s in specs if s["name"] == "github"]
        self.assertEqual(len(gh), 1)
        self.assertTrue(Path(gh[0]["command"][-1]).name == "github_mcp.py")
        own = {"name": "github", "command": ["{python}", "mine.py"]}
        specs = server_probe("print(json.dumps(server._mcp_specs()))", {"github_enabled": True, "mcp_servers": [own]})
        self.assertEqual([s["command"][-1] for s in specs if s["name"] == "github"][0].split(os.sep)[-1][-7:], "mine.py")

    def test_set_github_validates_saves_and_keeps_other_settings(self):
        out = server_probe(
            "r={}\n"
            "try: server._set_github({'enabled':'yes'})\n"
            "except ValueError as e: r['err']=str(e)\n"
            "r['saved']=server._set_github({'enabled':True})\n"
            "r['names']=[s['name'] for s in server._mcp_specs()]\n"
            "r['file']=json.load(open(server.SETTINGS_PATH))\n"
            "server._MCP.stop_all()\nprint(json.dumps(r))", {"browser_mode": "sandbox"})
        self.assertIn("true or false", out["err"])
        self.assertEqual(out["saved"], {"enabled": True})
        self.assertIn("github", out["names"])
        self.assertEqual(out["file"]["github_enabled"], True)
        self.assertEqual(out["file"]["browser_mode"], "sandbox")  # shared writer keeps the other keys


class UiAndBundle(unittest.TestCase):
    def test_control_keyboard_and_phone_width(self):
        for s in ('id="ghBtn" type="button"', '<dialog id="ghDlg" aria-labelledby="ghTitle">', 'id="ghOn"', "/api/github", "#ghBtn:focus-visible"):
            self.assertIn(s, HTML)
        self.assertRegex(HTML, r"(?m)^#brDlg,#ghDlg\{[^}]*max-height[^}]*overflow:auto")
        self.assertRegex(HTML, r"@media \(max-width:600px\)\{#brDlg,#ghDlg")

    def test_ships_as_a_plain_script(self):
        self.assertIn("github_mcp.py", (ROOT / "check-bundle.py").read_text(encoding="utf-8"))
        self.assertNotIn("github_mcp", (ROOT / "core-files.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
