"""Real-browser check of the Browser control: page never scrolls (desktop + phone + 1.5x scale), dialog opens
by keyboard, saving works, and a screenshot result renders as an <img> in the activity log.
Skips when Playwright or its Chromium is missing. Run: python atlas-rust-desktop/validation-tests/e2e_browser_controls.py"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ATLAS = Path(__file__).resolve().parents[1] / "src-tauri" / "resources" / "atlas"
PORT = 18433
PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class BrowserControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="atlas-br-e2e-")
        Path(cls.tmp, "settings.json").write_text(json.dumps(
            {"server_port": PORT, "upstream_port": 18434, "embedding_model": "", "mcp_auto_tools": False}), encoding="utf-8")
        env = dict(os.environ, ATLAS_DATA_DIR=cls.tmp, ATLAS_OBSERVABILITY_DB=os.path.join(cls.tmp, "o.sqlite3"))
        cls.proc = subprocess.Popen([sys.executable, "server.py"], cwd=ATLAS, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1)
                break
            except OSError:
                time.sleep(0.15)
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:
            cls.tearDownClass()
            raise unittest.SkipTest(f"chromium not available: {exc}")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "browser", None):
            cls.browser.close()
        if getattr(cls, "pw", None):
            cls.pw.stop()
        cls.proc.kill()

    def page(self, w, h, dsf=1):
        p = self.browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=dsf)
        p.goto(f"http://127.0.0.1:{PORT}/")
        p.wait_for_selector("#brBtn")
        return p

    def no_scroll(self, p):
        r = p.evaluate("()=>{const s=document.scrollingElement;return [s.scrollHeight-s.clientHeight,s.scrollWidth-s.clientWidth,"
                       "document.querySelector('#brBtn').getBoundingClientRect().right<=innerWidth]}")
        self.assertEqual(r[0], 0)
        self.assertEqual(r[1], 0)

    def test_page_never_scrolls_at_sizes(self):
        for w, h, dsf in ((1400, 900, 1), (1400, 900, 1.5), (390, 800, 1), (320, 600, 1)):
            p = self.page(w, h, dsf)
            self.no_scroll(p)
            p.focus("#brBtn"); p.keyboard.press("Enter")
            p.wait_for_selector("#brDlg[open]")
            self.no_scroll(p)
            box = p.evaluate("()=>{const r=document.querySelector('#brDlg').getBoundingClientRect();return [r.width<=innerWidth+1,r.height<=innerHeight+1]}")
            self.assertEqual(box, [True, True], (w, h, dsf))
            p.close()

    def test_keyboard_save_updates_state(self):
        p = self.page(1400, 900)
        p.wait_for_function("document.querySelector('#brState').textContent !== '...'")
        p.focus("#brBtn"); p.keyboard.press("Enter")
        p.wait_for_selector("#brDlg[open]")
        p.wait_for_function("document.querySelector('#brInfo').textContent !== 'Loading...'")
        p.select_option("#brMode", "sandbox")
        p.focus("#brSave"); p.keyboard.press("Enter")
        p.wait_for_function("document.querySelector('#brInfo').textContent.startsWith('Saved')")
        self.assertEqual(p.inner_text("#brState"), "sandbox")
        p.uncheck("#brOn"); p.click("#brSave")
        p.wait_for_function("document.querySelector('#brState').textContent==='off'")
        p.keyboard.press("Escape")
        self.assertFalse(p.evaluate("document.querySelector('#brDlg').open"))
        p.close()

    def test_screenshot_renders_as_image(self):
        p = self.page(1400, 900)
        p.evaluate("document.querySelector('#executionPanel').style.display = 'flex'")
        p.evaluate("""(png)=>{renderExecutionLog([{type:'mcp.tool',timestamp:Date.now()/1000,data:{server:'browser',tool:'browser_screenshot',
          status:'EXECUTED_UNVERIFIED',result:{content:[{type:'image',mimeType:'image/png',data:png},{type:'image',mimeType:'text/html',data:'x'}]}}}]);}""", PNG)
        p.click(".exec-header")
        self.assertEqual(p.locator(".exec-shots img").count(), 1)  # the fake text/html "image" is refused
        self.assertNotIn(PNG, p.inner_text(".exec-body"))
        p.close()


if __name__ == "__main__":
    unittest.main()
