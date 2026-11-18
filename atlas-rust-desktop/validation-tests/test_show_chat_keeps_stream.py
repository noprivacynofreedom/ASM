"""LLAMA-SWAP then CHAT must not rebuild #log while a reply streams (2026-11-18: the reply looked cancelled)."""
import re
import unittest
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "src-tauri" / "resources" / "atlas" / "index.html"


class ShowChatKeepsStream(unittest.TestCase):
    def test_show_page_chat_skips_rebuild_while_streaming(self):
        src = HTML.read_text(encoding="utf-8")
        body = re.search(r"function showPage\(page\) \{(.*?)\n\}\n", src, re.S).group(1)
        chat_branch = body.split('page === "chat"', 1)[1].split("} else if", 1)[0]
        self.assertNotRegex(chat_branch, r"(?m)^\s*renderLog\(\);", "unguarded renderLog() in showPage('chat')")
        self.assertIn("if (!ctrl) renderLog();", chat_branch)


if __name__ == "__main__":
    unittest.main()
