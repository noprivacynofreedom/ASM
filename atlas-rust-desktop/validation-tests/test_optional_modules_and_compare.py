"""Contract tests for optional_modules (Phase 0) and compare_mode (Phase 1A)."""
import json
import os
import tempfile
import unittest
from pathlib import Path

import compare_mode
import optional_modules

ATLAS_DIR = Path(__file__).resolve().parents[1] / "src-tauri" / "resources" / "atlas"
HTML_PATH = ATLAS_DIR / "index.html"


class OptionalModulesTests(unittest.TestCase):
    def test_defaults_and_non_destructive_update(self):
        with tempfile.TemporaryDirectory(prefix="atlas-mod-") as tmp:
            settings_path = os.path.join(tmp, "settings.json")
            original = {
                "server_port": 8090,
                "upstream_port": 8088,
                "workspace_dir": "D:\\work\\demo",
                "bot_docs": {"architect": ["notes.md"]},
            }
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(original, f)

            resolved = optional_modules.resolve_modules(original)
            self.assertTrue(resolved["compare"])
            self.assertTrue(resolved["docs_canvas"])
            self.assertTrue(resolved["deep_research"])
            self.assertTrue(resolved["cookbook"])
            self.assertTrue(resolved["skills_registry"])
            self.assertFalse(resolved["scheduler"])
            self.assertFalse(resolved["productivity_mcp"])

            updated = optional_modules.update_modules(settings_path, {"compare": False, "scheduler": True})
            self.assertFalse(updated["compare"])
            self.assertTrue(updated["scheduler"])

            with open(settings_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["upstream_port"], 8088)
            self.assertEqual(saved["workspace_dir"], "D:\\work\\demo")
            self.assertEqual(saved["bot_docs"], {"architect": ["notes.md"]})
            self.assertFalse(saved["modules"]["compare"])
            self.assertTrue(saved["modules"]["scheduler"])

    def test_rejects_unknown_or_non_boolean_flags(self):
        with tempfile.TemporaryDirectory(prefix="atlas-mod-bad-") as tmp:
            settings_path = os.path.join(tmp, "settings.json")
            with self.assertRaises(ValueError):
                optional_modules.update_modules(settings_path, {"not_a_real_module": True})
            with self.assertRaises(ValueError):
                optional_modules.update_modules(settings_path, {"compare": "yes"})
            with self.assertRaises(ValueError):
                optional_modules.update_modules(settings_path, {})

    def test_catalog_response_shape(self):
        res = optional_modules.catalog_response({"modules": {"compare": False}})
        self.assertTrue(res["ok"])
        self.assertFalse(res["flags"]["compare"])
        by_id = {m["id"]: m for m in res["modules"]}
        self.assertIn("compare", by_id)
        self.assertTrue(by_id["compare"]["implemented"])
        self.assertFalse(by_id["compare"]["enabled"])


class BlindCompareTests(unittest.TestCase):
    def test_blind_masking_vote_reveal_and_leaderboard(self):
        def fake_caller(model_id, prompt, **_kwargs):
            return f"Answer from secret-{model_id} for {prompt}", f"Machine-{model_id}"

        run = compare_mode.run_compare(
            "Explain Raft consensus briefly",
            ["coder", "cloud:gemini"],
            caller=fake_caller,
        )
        self.assertTrue(run["ok"])
        self.assertTrue(run["blind"])
        self.assertFalse(run["revealed"])
        self.assertEqual(len(run["entries"]), 2)
        for entry in run["entries"]:
            self.assertNotIn("model", entry)
            self.assertNotIn("machine", entry)
            self.assertTrue(entry["ok"])
            self.assertIn(entry["slot"], ("A", "B"))

        with tempfile.TemporaryDirectory(prefix="atlas-cmp-") as tmp:
            hist_path = os.path.join(tmp, "compare_history.jsonl")
            voted = compare_mode.vote_compare(run["compare_id"], "A", history_path=hist_path)
            self.assertTrue(voted["ok"])
            self.assertTrue(voted["revealed"])
            self.assertFalse(voted["blind"])
            self.assertEqual(voted["winner_slot"], "A")
            self.assertIn(voted["winner_model"], ("coder", "cloud:gemini"))
            for entry in voted["entries"]:
                self.assertIn("model", entry)
                self.assertIn("machine", entry)

            # Second run with a tie vote
            run2 = compare_mode.run_compare(
                "Compare TCP vs UDP",
                ["coder", "cloud:gemini"],
                caller=fake_caller,
            )
            tied = compare_mode.vote_compare(run2["compare_id"], "tie", history_path=hist_path)
            self.assertEqual(tied["winner_slot"], "tie")
            self.assertIsNone(tied["winner_model"])

            history = compare_mode.list_history(hist_path, limit=10)
            self.assertEqual(len(history), 2)
            board = compare_mode.leaderboard(hist_path)
            self.assertEqual(len(board), 2)
            total_wins = sum(r["wins"] for r in board)
            total_ties = sum(r["ties"] for r in board)
            self.assertEqual(total_wins, 1)
            self.assertEqual(total_ties, 2)  # both models got 1 tie each

    def test_partial_failure_and_reveal_without_vote(self):
        def flaky_caller(model_id, prompt, **_kwargs):
            if model_id == "broken-model":
                raise RuntimeError("upstream offline")
            return "Healthy response", "Local"

        run = compare_mode.run_compare("Hello", ["coder", "broken-model"], caller=flaky_caller)
        ok_flags = sorted(e["ok"] for e in run["entries"])
        self.assertEqual(ok_flags, [False, True])

        rev = compare_mode.reveal_compare(run["compare_id"])
        self.assertTrue(rev["revealed"])
        self.assertIsNone(rev["winner_slot"])
        models = {e["model"] for e in rev["entries"]}
        self.assertEqual(models, {"coder", "broken-model"})

    def test_validation_errors(self):
        with self.assertRaises(ValueError):
            compare_mode.run_compare("", ["coder", "mentor"])
        with self.assertRaises(ValueError):
            compare_mode.run_compare("hi", ["coder"])
        with self.assertRaises(ValueError):
            compare_mode.run_compare("hi", ["a", "b", "c", "d", "e"])
        with self.assertRaises(KeyError):
            compare_mode.reveal_compare("cmp-does-not-exist")


class UiContractTests(unittest.TestCase):
    def test_modules_and_compare_dialogs_and_slash_commands(self):
        html = HTML_PATH.read_text(encoding="utf-8")
        self.assertIn('id="modulesDlg"', html)
        self.assertIn('id="compareDlg"', html)
        self.assertIn('"/compare"', html)
        self.assertIn('"/modules"', html)
        self.assertIn("async function openCompareDialog(", html)
        self.assertIn("async function openModulesDialog(", html)


if __name__ == "__main__":
    unittest.main()
