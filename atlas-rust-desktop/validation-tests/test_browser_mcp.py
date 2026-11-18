import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ATLAS = Path(__file__).resolve().parent.parent / "src-tauri" / "resources" / "atlas"
sys.path.insert(0, str(ATLAS))
import browser_mcp  # noqa: E402
import mcp_chat  # noqa: E402

try:
    import playwright  # noqa: F401
    HAVE_PW = True
except ImportError:
    HAVE_PW = False


class UrlGuard(unittest.TestCase):
    def test_allowed(self):
        for u in ("https://example.com/x", "http://8.8.8.8/", "data:text/html,<p>hi</p>", "about:blank"):
            self.assertEqual(browser_mcp.url_blocked(u), "", u)

    def test_blocked(self):
        for u in ("file:///etc/passwd", "chrome://settings", "about:config", "javascript:alert(1)",
                  "http://localhost:8080", "http://foo.localhost/", "http://127.0.0.1/", "http://10.0.0.5/",
                  "http://192.168.1.1/", "http://169.254.169.254/", "http://0.0.0.0/", "http://[::1]/",
                  "http://2130706433/", "http://0x7f000001/", "http://printer.local/", "ftp://x/y", "view-source:http://a"):
            self.assertTrue(browser_mcp.url_blocked(u), u)

    def test_mapped_ipv6_and_octal_forms(self):
        for u in ("http://[::ffff:127.0.0.1]/", "http://[::ffff:10.0.0.1]/", "http://0177.0.0.1/", "http://127.1/"):
            self.assertTrue(browser_mcp.url_blocked(u), u)

    def test_allow_local(self):
        self.assertEqual(browser_mcp.url_blocked("http://localhost/", True), "")
        self.assertEqual(browser_mcp.url_blocked("file:///a", True), "")
        self.assertTrue(browser_mcp.url_blocked("chrome://x", True))
        self.assertTrue(browser_mcp.url_blocked("javascript:1", True))


class Mode(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(browser_mcp.resolve_mode({"ATLAS_BROWSER_MODE": "sandbox"}), "sandbox")
        self.assertEqual(browser_mcp.resolve_mode({"ATLAS_BROWSER_MODE": "host"}), "host")
        self.assertEqual(browser_mcp.resolve_mode({"ATLAS_BROWSER_MODE": "bogus", "DISPLAY": ":0"}),
                         browser_mcp.resolve_mode({"DISPLAY": ":0"}))

    def test_allow_local_env(self):
        self.assertFalse(browser_mcp.allow_local({}))
        self.assertTrue(browser_mcp.allow_local({"ATLAS_BROWSER_ALLOW_LOCAL": "1"}))


class Tiers(unittest.TestCase):
    def test_tiers_cover_all_tools(self):
        names = {t[0] for t in browser_mcp.TOOLS}
        self.assertEqual(len(names), 10)
        for n in names:
            self.assertIn(n, mcp_chat.TOOL_TIERS, n)
        for n in ("browser_get_text", "browser_screenshot", "browser_tabs", "browser_wait"):
            self.assertEqual(mcp_chat.TOOL_TIERS[n], "read")
        for n in ("browser_open", "browser_click", "browser_type", "browser_press", "browser_eval", "browser_close"):
            self.assertEqual(mcp_chat.TOOL_TIERS[n], "write")


class Protocol(unittest.TestCase):
    def test_handle(self):
        b = object()
        self.assertIsNone(browser_mcp.handle(b, {"method": "notifications/initialized"}))
        r = browser_mcp.handle(b, {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-03-26")
        r = browser_mcp.handle(b, {"id": 2, "method": "tools/list"})
        self.assertEqual(len(r["result"]["tools"]), 10)
        r = browser_mcp.handle(b, {"id": 3, "method": "tools/call", "params": {"name": "nope"}})
        self.assertEqual(r["error"]["code"], -32602)
        r = browser_mcp.handle(b, {"id": 4, "method": "bogus"})
        self.assertEqual(r["error"]["code"], -32601)

    def test_tool_exception_is_iserror(self):
        class B:
            def browser_tabs(self, a):
                raise RuntimeError("boom")
        r = browser_mcp.handle(B(), {"id": 1, "method": "tools/call", "params": {"name": "browser_tabs"}})
        self.assertTrue(r["result"]["isError"])

    def test_open_blocked_url_without_playwright(self):
        b = browser_mcp.Browser()
        r = browser_mcp.handle(b, {"id": 1, "method": "tools/call",
                                   "params": {"name": "browser_open", "arguments": {"url": "file:///etc/passwd"}}})
        self.assertTrue(r["result"].get("isError"))

    def test_stdio_subprocess(self):
        inp = "\n".join(json.dumps(m) for m in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            "garbage-not-object",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})) + "\n"
        p = subprocess.run([sys.executable, str(ATLAS / "browser_mcp.py")], input=inp, capture_output=True,
                           text=True, timeout=30)
        lines = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
        self.assertEqual([l["id"] for l in lines], [1, 2])


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class RealBrowser(unittest.TestCase):
    def test_smoke(self):
        os.environ["ATLAS_BROWSER_MODE"] = "sandbox"
        b = browser_mcp.Browser()
        try:
            url = "data:text/html,<title>T</title><button id=b onclick=\"this.textContent='clicked'\">go</button>"
            b.browser_open({"url": url})
            self.assertIn("go", b.browser_get_text({}))
            b.browser_click({"selector": "#b"})
            self.assertIn("clicked", b.browser_get_text({"selector": "#b"}))
            self.assertEqual(b.browser_eval({"js": "1+1"}), "2")
            self.assertEqual(b.browser_screenshot({})[0]["mimeType"], "image/png")
            with self.assertRaises(Exception):
                b.browser_open({"url": "http://127.0.0.1:1/"})
        finally:
            b.close()


if __name__ == "__main__":
    unittest.main()
