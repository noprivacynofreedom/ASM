"""Regression: strict chat templates reject a system message that is not first or not unique
("System message must be at the beginning" -> llama-swap HTTP 500)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "atlas-rust-desktop" / "src-tauri" / "resources" / "atlas"))
from mcp_chat import normalize_system_messages  # noqa: E402


class NormalizeSystemMessages(unittest.TestCase):
    def test_no_system_is_unchanged(self):
        msgs = [{"role": "user", "content": "hi"}]
        self.assertEqual(normalize_system_messages(msgs), msgs)

    def test_late_system_moves_first(self):
        out = normalize_system_messages([
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
            {"role": "system", "content": "late"},
        ])
        self.assertEqual(out[0], {"role": "system", "content": "late"})
        self.assertEqual([m["role"] for m in out], ["system", "user", "assistant"])

    def test_multiple_systems_merge_to_one(self):
        out = normalize_system_messages([
            {"role": "system", "content": "A"},
            {"role": "user", "content": "q"},
            {"role": "system", "content": "B"},
        ])
        self.assertEqual(sum(m["role"] == "system" for m in out), 1)
        self.assertEqual(out[0]["content"], "A\n\nB")

    def test_multimodal_system_content_is_preserved(self):
        out = normalize_system_messages([
            {"role": "system", "content": [{"type": "text", "text": "A"}]},
            {"role": "system", "content": "B"},
        ])
        self.assertEqual(out[0]["content"], [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}])


if __name__ == "__main__":
    unittest.main()
