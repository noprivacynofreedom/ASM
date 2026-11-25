"""Contract tests for Google-style Action History cards in Atlas Chat replies."""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

import no_real_keys  # noqa: F401
import mcp_chat
import test_suite_mcp


ATLAS_DIR = pathlib.Path(__file__).resolve().parent.parent / "src-tauri" / "resources" / "atlas"
TESTS_DIR = pathlib.Path(__file__).resolve().parent


class TestActionHistoryBackendAndUi(unittest.TestCase):
    def test_as_sse_includes_sanitized_atlas_tool_events(self):
        completion = {
            "id": "chatcmpl-test",
            "model": "qwen-test",
            "choices": [{"message": {"role": "assistant", "content": "Done."}, "finish_reason": "stop"}],
        }
        events = [
            {
                "tool": "atlas_read_file",
                "server": "atlas_commander",
                "status": "EXECUTED_UNVERIFIED",
                "adapter_duration_ms": 42.6,
                "args_preview": '{"path": "server.py"}',
                "call_id": "call_atlas_1234",
            },
            {
                "tool": "write_file",
                "server": "atlas_commander",
                "status": "FAILED",
                "duration_ms": 18.2,
                "error": "PermissionError: denied",
                "trace_id": "tr-9981",
            },
        ]
        sse = mcp_chat.as_sse(completion, events)
        first_line = sse.splitlines()[0]
        self.assertTrue(first_line.startswith("data: "))
        payload = json.loads(first_line[len("data: "):])
        self.assertIn("atlas_tool_events", payload)
        self.assertEqual(len(payload["atlas_tool_events"]), 2)
        self.assertEqual(payload["atlas_tool_events"][0]["tool"], "atlas_read_file")
        self.assertEqual(payload["atlas_tool_events"][0]["duration_ms"], 42.6)
        self.assertEqual(payload["atlas_tool_events"][0]["trace_id"], "call_atlas_1234")
        self.assertEqual(payload["atlas_tool_events"][1]["status"], "FAILED")
        self.assertIn("PermissionError", payload["atlas_tool_events"][1]["error"])

    def test_index_html_has_action_history_card_icons_and_persistence(self):
        html = (ATLAS_DIR / "index.html").read_text(encoding="utf-8")
        for marker in (
            ".ah-card",
            ".ah-cards",
            ".ah-tree",
            ".ah-indent",
            ".ah-indent.md",
            ".ah-bot-pill",
            "AH_SVG",
            "function ahClassifyTool(",
            "function ahClassifySwarmEntry(",
            "function inferSwarmDeliveryEvents(",
            "function ahBindCopyTrace(",
            "function renderActionHistoryHtml(",
            "SWARM_LOG_SPLIT_RE",
            "Swarm action history",
            "j.atlas_tool_events",
            "j.atlas_error",
            "data-copy-trace",
            "openTestSuiteOverlay(",
            "const displayOut = Number(realUsage && realUsage.completion_tokens) || predictedN || nOut;",
            "const reportedTokens = Number(realUsage && realUsage.completion_tokens) || predictedN || (nThink + nOut);",
        ):
            self.assertIn(marker, html, f"Expected Action History / Test Suite marker {marker!r} in index.html")
        self.assertNotIn("window.open('/test-suite'", html)
        for legacy in (
            '<li class="tl-stage-group">',
            '<span class="tl-kind">',
            '<div class="tl-nested">',
            '<details class="think"',
            '<details class="sv-steps"',
        ):
            self.assertNotIn(legacy, html, f"Legacy non-Action-History markup {legacy!r} should not remain in index.html")

    def test_swarm_replies_action_history_js_contract(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        proc = subprocess.run(
            [node, str(TESTS_DIR / "test_swarm_action_history.js")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, f"test_swarm_action_history.js failed:\n{proc.stdout}\n{proc.stderr}")

    def test_suite_default_features_seed_idempotently_and_tiles_support_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = test_suite_mcp.seed_default_features(tmp)
            self.assertGreaterEqual(first["added"], 10)
            second = test_suite_mcp.seed_default_features(tmp)
            self.assertEqual(second["added"], 0)
            self.assertEqual(second["total"], first["total"])
        ts_html = (ATLAS_DIR / "test_suite.html").read_text(encoding="utf-8")
        for marker in ("seed_defaults", "data-note-toggle-fid", "data-note-form-fid", "#07080b", "#22c55e"):
            self.assertIn(marker, ts_html)


if __name__ == "__main__":
    unittest.main()
