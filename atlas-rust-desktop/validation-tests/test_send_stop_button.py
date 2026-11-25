"""Regression tests for normal-chat Send / Stop button visibility, hit-testing, and lifecycle.

Guards against all root causes of the normal chat Stop / Send button disappearing:
  1. #atomicToast / #atlasDevFab covering or blocking clicks on #send / #stop
  2. Vertical flex overflow pushing form.send below main { overflow: hidden }
  3. Horizontal squeezing / wrapping clipping #send / #stop in form.send (including with #brBtn + #ghBtn)
  4. Async gaps, concurrency races, and missing finally cleanup in send(), /compact, teamRun(), and queue handoffs
  5. Syntax corruption in any <script> block of index.html
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src-tauri" / "resources" / "atlas" / "index.html"


def _css_rule(src: str, selector: str) -> str:
    m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", src)
    return m.group(1) if m else ""


class SendStopButtonContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding="utf-8")

    def test_all_script_blocks_parse_cleanly(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        scripts = re.findall(r"<script\b[^>]*>([\s\S]*?)</script>", self.html, flags=re.I)
        self.assertGreaterEqual(len(scripts), 1, "index.html must contain at least one <script> block")
        for idx, body in enumerate(scripts):
            with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as tmp:
                tmp.write(body)
                tmp_path = tmp.name
            try:
                proc = subprocess.run([node, "--check", tmp_path], capture_output=True, text=True)
                self.assertEqual(
                    proc.returncode,
                    0,
                    f"index.html <script> #{idx} has a syntax error:\n{proc.stderr}",
                )
            finally:
                os.unlink(tmp_path)

    def test_composer_layout_keeps_send_and_stop_visible(self):
        form_css = _css_rule(self.html, "form.send")
        self.assertIn("flex:none", form_css)
        self.assertIn("flex-wrap:wrap", form_css)

        send_stop_css = _css_rule(self.html, "#send,#stop")
        self.assertIn("flex:none", send_stop_css)
        self.assertIn("white-space:nowrap", send_stop_css)

        hidden_css = _css_rule(self.html, "#send[hidden],#stop[hidden]")
        self.assertIn("display:none", hidden_css)

        files_empty_css = _css_rule(self.html, "#files:empty")
        self.assertIn("display:none", files_empty_css)

        # AGENTS.md §3: blocks above/below #log must shrink before form.send can be pushed off-screen.
        for selector in (".head", ".activity-companion", "#swarmBar", "#approvals", "#files"):
            rule = _css_rule(self.html, selector)
            self.assertIn("flex:0 1 auto", rule, f"{selector} must use flex:0 1 auto")
            self.assertIn("min-height:0", rule, f"{selector} must set min-height:0")
            self.assertNotIn("flex:none", rule, f"{selector} must not use flex:none")
            self.assertIn("max-height:", rule, f"{selector} must cap max-height")
            self.assertRegex(rule, r"overflow(?:-y)?\s*:\s*auto", f"{selector} must scroll internally")

        self.assertNotRegex(self.html, r"(?m)^[^\n]*#(?:brBtn|ghBtn)[^\n{]*\{[^}]*font:inherit")

    def test_overlays_do_not_cover_or_intercept_send_stop(self):
        toast_css = _css_rule(self.html, "#atomicToast")
        self.assertNotIn("bottom:", toast_css, "#atomicToast must not sit over bottom-right Send/Stop")
        self.assertIn("top:", toast_css)
        self.assertIn("pointer-events:none", toast_css)
        self.assertIn("visibility:hidden", toast_css)

        toast_show_css = _css_rule(self.html, "#atomicToast.show")
        self.assertIn("pointer-events:auto", toast_show_css)
        self.assertIn("visibility:visible", toast_show_css)

        fab_css = _css_rule(self.html, "#atlasDevFab")
        self.assertNotIn("bottom:18px", fab_css, "#atlasDevFab must not overlap Send/Stop at bottom:18px")

    def test_sync_composer_buttons_and_lifecycle_guards(self):
        self.assertIn("function syncComposerButtons()", self.html)
        sync_body = re.search(r"function syncComposerButtons\(\)\{([\s\S]*?)\n\}", self.html)
        self.assertIsNotNone(sync_body)
        self.assertIn("ctrl || queueRunning || queueDrainPromise", sync_body.group(1))

        # renderQueue() must reconcile composer buttons before any early return
        rq = re.search(r"function renderQueue\(\)\{([\s\S]*?)\n\}", self.html)
        self.assertIsNotNone(rq)
        self.assertLess(rq.group(1).index("syncComposerButtons()"), rq.group(1).index("if(!log) return"))

        # showPage("chat") must not force inline display:flex on empty #files and must sync composer buttons
        sp = re.search(r"function showPage\(page\) \{([\s\S]*?)\n\}", self.html)
        self.assertIsNotNone(sp)
        chat_branch = sp.group(1).split('} else if (page === "ops")')[0]
        self.assertNotIn('filesBar.style.display = "flex"', chat_branch)
        self.assertIn("syncComposerButtons()", chat_branch)

        # send() must guard concurrency, claim ctrl before vision/compaction awaits, and clean up in finally
        send_start = self.html.index("async function send(text, options={}){")
        send_end = self.html.index("/* ---------- bot editor ----------")
        send_src = self.html[send_start:send_end]
        self.assertIn("if (ctrl)", send_src)
        self.assertIn("const myCtrl = new AbortController();", send_src)
        self.assertLess(send_src.index("const myCtrl = new AbortController();"), send_src.index("/api/vision"))
        self.assertLess(send_src.index("const myCtrl = new AbortController();"), send_src.index("maybeAutoCompact("))
        self.assertIn("signal:myCtrl.signal", send_src.replace(" ", ""))
        self.assertIn("maybeAutoCompact(c, b, myCtrl.signal)", send_src)
        self.assertIn("isSwarmStart(text)", send_src)
        self.assertIn("finally {", send_src)
        self.assertIn("if (ctrl === myCtrl) ctrl = null;", send_src)

        # compactChat and manual /compact must support AbortSignal and Stop button
        self.assertIn("async function compactChat(c, b, upto, reason, signal=null)", self.html)
        self.assertIn('await compactChat(c, b, upto, "manual", myCtrl.signal)', self.html)

        # teamRun must clean up ctrl + buttons in finally
        tr_start = self.html.index("async function teamRun(")
        tr_end = self.html.index('$("#teamBtn").onclick')
        tr_src = self.html[tr_start:tr_end]
        self.assertIn("const myCtrl = new AbortController();", tr_src)
        self.assertIn("finally {", tr_src)
        self.assertIn("syncComposerButtons()", tr_src)


if __name__ == "__main__":
    unittest.main()
