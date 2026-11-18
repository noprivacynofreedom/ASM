"""Validation tests for chat history organization, swarm library clarity, and anti-lag improvements."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "src-tauri" / "resources" / "atlas"
if str(ATLAS) not in sys.path:
    sys.path.insert(0, str(ATLAS))


class BackendStreamlineTests(unittest.TestCase):
    def test_load_state_caches_by_mtime_and_size(self):
        import server

        with tempfile.TemporaryDirectory(prefix="atlas-cache-") as tmp:
            data_path = os.path.join(tmp, "data.json")
            payload = {"bots": [{"id": "b1", "name": "Bot 1"}], "chats": [{"id": "c1", "title": "Hello", "messages": []}]}
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)

            orig_data = server.DATA
            try:
                server.DATA = data_path
                server._STATE_CACHE.update(path=None, mtime_ns=None, size=None, data=None, raw_bytes=None, ensured_bots=None)
                first = server._load_state()
                second = server._load_state()
                self.assertIs(first, second, "_load_state should return the cached dict when mtime/size are unchanged")

                # Update file content and size; cache must refresh
                payload["chats"].append({"id": "c2", "title": "Second", "messages": []})
                with open(data_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f)
                third = server._load_state()
                self.assertIsNot(first, third)
                self.assertEqual(len(third["chats"]), 2)
            finally:
                server.DATA = orig_data
                server._STATE_CACHE.update(path=None, mtime_ns=None, size=None, data=None, raw_bytes=None, ensured_bots=None)

    def test_summarize_chat_strips_messages_and_classifies_swarm(self):
        import server

        normal = {
            "id": "chat-1",
            "botId": "b1",
            "title": "   Fix   login   bug  ",
            "updatedAt": 1700000000000,
            "messages": [
                {"role": "user", "content": "How do I fix the login bug?"},
                {"role": "assistant", "content": "Check the session cookie expiry."},
            ],
        }
        s_normal = server._summarize_chat(normal)
        self.assertNotIn("messages", s_normal)
        self.assertFalse(s_normal["is_swarm"])
        self.assertEqual(s_normal["kind"], "chat")
        self.assertEqual(s_normal["message_count"], 2)
        self.assertEqual(s_normal["title"], "Fix login bug")
        self.assertIn("session cookie", s_normal["preview"])

        swarm_lead = {
            "id": "sw123456-final",
            "botId": "Swarm Lead",
            "title": "Build a calculator app",
            "messages": [{"role": "assistant", "content": "Done."}],
        }
        s_lead = server._summarize_chat(swarm_lead)
        self.assertTrue(s_lead["is_swarm"])
        self.assertEqual(s_lead["kind"], "swarm_lead")
        self.assertEqual(s_lead["run_id"], "sw123456")

    def test_enrich_swarm_runs_adds_summary_and_strips_logs_when_requested(self):
        import server

        payload = {
            "runs": [
                {
                    "run_id": "sw1",
                    "goal": "Implement dark mode and fix sidebar scroll",
                    "category": "code",
                    "state": "running",
                    "lead": {"conversation_id": "sw1-final", "lines": ["a", "b"], "routes": ["r1"]},
                    "chats": [
                        {"conversation_id": "sw1-1", "bot": "SDE", "state": "done", "phase": "done", "seconds": 5, "task": "edit css", "lines": ["l1"], "routes": ["r1"]},
                        {"conversation_id": "sw1-2", "bot": "QA", "state": "running", "phase": "test", "seconds": 2, "task": "run tests", "lines": ["l2"], "routes": ["r2"]},
                    ],
                }
            ]
        }
        full = server._enrich_swarm_runs(payload, summary_only=False)
        self.assertEqual(full["runs"][0]["summary"], {"total": 2, "done": 1, "running": 1, "failed": 0, "queued": 0})
        self.assertEqual(len(full["runs"][0]["worker_summaries"]), 2)
        self.assertIn("lines", full["runs"][0]["chats"][0])

        slim = server._enrich_swarm_runs(payload, summary_only=True)
        self.assertNotIn("lines", slim["runs"][0]["chats"][0])
        self.assertNotIn("routes", slim["runs"][0]["chats"][0])
        self.assertNotIn("lines", slim["runs"][0]["lead"])

    def test_archive_chat_and_swarm_run_helpers_and_routes(self):
        import server

        archived_chat = {"id": "c-arch", "botId": "b1", "title": "Old chat", "archived": True, "messages": []}
        active_chat = {"id": "c-act", "botId": "b1", "title": "Active chat", "messages": []}
        self.assertTrue(server._summarize_chat(archived_chat)["archived"])
        self.assertFalse(server._summarize_chat(active_chat)["archived"])

        with tempfile.TemporaryDirectory(prefix="atlas-arch-") as tmp:
            data_path = os.path.join(tmp, "data.json")
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump({"swarm_archived": {"sw1": True, "sw2": False}}, f)
            orig_data = server.DATA
            try:
                server.DATA = data_path
                server._STATE_CACHE.update(path=None, mtime_ns=None, size=None, data=None, raw_bytes=None, ensured_bots=None)
                enriched = server._enrich_swarm_runs({
                    "runs": [
                        {"run_id": "sw1", "goal": "First", "chats": [], "archived": False},
                        {"run_id": "sw2", "goal": "Second", "chats": [], "archived": True},
                    ]
                })
                by_id = {r["run_id"]: r for r in enriched["runs"]}
                self.assertTrue(by_id["sw1"]["archived"])
                self.assertTrue(by_id["sw1"]["manually_archived"])
                self.assertFalse(by_id["sw2"]["archived"])
                self.assertFalse(by_id["sw2"]["manually_archived"])
            finally:
                server.DATA = orig_data
                server._STATE_CACHE.update(path=None, mtime_ns=None, size=None, data=None, raw_bytes=None, ensured_bots=None)

        srv_src = (ATLAS / "server.py").read_text(encoding="utf-8")
        self.assertIn('/api/conversations/', srv_src)
        self.assertIn('/api/ops/swarm/runs/', srv_src)
        self.assertIn('"/archive"', srv_src)


class UiAndFrameStreamlineTests(unittest.TestCase):
    def test_index_html_has_grouped_history_windowed_log_and_bounded_swarm_bar(self):
        html = (ATLAS / "index.html").read_text(encoding="utf-8")
        # Chat history grouping, pinning, search debounce, DocumentFragment
        for marker in ("PINNED", "TODAY", "YESTERDAY", "EARLIER", "chatMatchesQuery", "replaceChildren", "LOG_PAGE_SIZE"):
            self.assertIn(marker, html, f"missing {marker} in index.html")
        self.assertIn("Load earlier messages", html)
        self.assertIn("same-sender", html)
        # Swarm bar & tree organization
        self.assertIn("ACTIVE RUNS", html)
        self.assertIn("RECENT RUNS", html)
        self.assertRegex(html, r"#swarmBar\{[^}]*flex:none[^}]*max-height:[^}]*overflow:auto")
        # Chat history archive / unarchive & unified Swarm Board
        self.assertIn("toggleChatArchive", html)
        self.assertIn("ARCHIVED", html)
        self.assertIn("archivedChatsOpen", html)
        self.assertIn("/archive", html)
        self.assertIn("atlas:open-swarm-board", html)
        self.assertIn("atlas:open-chat", html)

    def test_botlogs_js_has_poll_dedup_and_collapsible_archive(self):
        js = (ATLAS / "atlas_botlogs.js").read_text(encoding="utf-8")
        self.assertIn("details", js.lower())
        self.assertIn("setTimeout", js)
        self.assertIn("data-archive-run", js)
        self.assertIn("/api/ops/swarm/runs/", js)
        self.assertIn("Swarm Board", js)
        self.assertIn("atlas:open-chat", js)

    def test_swarm_run_uses_event_wakeup_instead_of_busy_join_poll(self):
        sr = (ATLAS / "swarm_run.py").read_text(encoding="utf-8")
        self.assertIn("lane_done", sr)
        self.assertIn("threading.Event", sr)

    def test_outer_frame_guards_polls_and_preserves_non_scrolling_root(self):
        app = (ROOT / "src" / "App.tsx").read_text(encoding="utf-8")
        style = (ROOT / "src" / "style.css").read_text(encoding="utf-8")
        node_css = (ROOT / "src" / "atlas-node.css").read_text(encoding="utf-8")

        self.assertIn("inFlightRef", app)
        self.assertIn("healthInFlightRef", app)
        self.assertIn("atlas:open-swarm-board", app)
        self.assertIn("Open Swarm Board", app)
        self.assertIn("overflow: hidden", style)
        self.assertIn(":focus-visible{outline:2px solid", node_css)
        self.assertIn("prefers-reduced-motion:reduce", node_css)

    def test_swarm_framework_docs_and_mcp_commander_tools(self):
        self.assertTrue((ATLAS / "prompts" / "swarm-framework.md").is_file())
        self.assertTrue((ATLAS / "agents" / "README.md").is_file())

        src_dir = ATLAS / "src"
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        import mcp_commander

        tool_names = {t["name"] for t in mcp_commander._swarm_tool_definitions()}
        for name in ("atlas_list_conversations", "atlas_swarm_runs", "atlas_archive_item"):
            self.assertIn(name, tool_names)

        orig_ro = os.environ.get("ATLAS_COMMANDER_READONLY")
        try:
            os.environ["ATLAS_COMMANDER_READONLY"] = "1"
            with self.assertRaisesRegex(ValueError, "READONLY"):
                mcp_commander.call_tool("atlas_archive_item", {"kind": "conversation", "item_id": "c1"})
            os.environ["ATLAS_COMMANDER_READONLY"] = "0"
            with self.assertRaisesRegex(ValueError, "Invalid item_id"):
                mcp_commander.call_tool("atlas_archive_item", {"kind": "conversation", "item_id": "../bad"})
        finally:
            if orig_ro is None:
                os.environ.pop("ATLAS_COMMANDER_READONLY", None)
            else:
                os.environ["ATLAS_COMMANDER_READONLY"] = orig_ro


if __name__ == "__main__":
    unittest.main()
