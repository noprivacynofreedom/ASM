"""The chat page must never scroll (CLAUDE.md section 8). Guards the CSS rules that keep it pinned."""
import re
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "src-tauri" / "resources" / "atlas" / "index.html").read_text(encoding="utf-8")


def rule(selector):
    m = re.search(r"(?m)^" + re.escape(selector) + r"\{([^}]*)\}", HTML)
    if not m:
        raise AssertionError(f"no CSS rule for {selector}")
    return m.group(1)


class PageNeverScrolls(unittest.TestCase):
    def test_page_is_pinned_to_the_window(self):
        self.assertIn("overflow:hidden", rule("html,body"))
        app = rule(".app")
        self.assertIn("height:100%", app)  # not 100vh: it rounds past the window under Windows display scaling
        self.assertNotIn("100vh", app)
        self.assertIn("overflow:hidden", app)
        self.assertIn("min-height:0", rule("main"))

    def test_blocks_around_the_log_cannot_push_the_page(self):
        self.assertIn("min-height:0", rule("#chatStage"))
        approvals = rule("#approvals")
        self.assertIn("max-height", approvals)
        self.assertIn("overflow:auto", approvals)

    def test_swarm_live_status_bar_rules(self):
        self.assertIn("@keyframes atlasSwarmSweep", HTML)
        self.assertIn("overflow:hidden", rule(".swarm-status-row"))
        self.assertIn('data-health="running"', HTML)
        self.assertIn('data-health="warn"', HTML)
        self.assertIn('data-health="bad"', HTML)
        self.assertIn("function swarmHealthState(", HTML)

    def test_llama_swap_return_to_chat_never_hides_main(self):
        self.assertIn('id="opsBackToChat"', HTML)
        self.assertIn('e.data.type === "atlas:show-chat"', HTML)
        self.assertIn('if (mainEl) mainEl.style.display = "flex";', HTML)
        self.assertNotIn('chatView.style.display = "none";', HTML)


if __name__ == "__main__":
    unittest.main()
