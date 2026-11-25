"""Contract tests for Phase 2B (Docs Canvas), 1B (Deep Research),
1C (Model Cookbook), and 2A (Governed Skills Registry)."""
import os
import tempfile
import unittest
from pathlib import Path

import docs_canvas
import model_cookbook
import research_pipeline
import skills_registry

ATLAS_DIR = Path(__file__).resolve().parents[1] / "src-tauri" / "resources" / "atlas"
HTML_PATH = ATLAS_DIR / "index.html"


class DocsCanvasTests(unittest.TestCase):
    def test_crud_and_reviewable_ai_diff_proposal(self):
        with tempfile.TemporaryDirectory(prefix="atlas-docs-") as tmp:
            created = docs_canvas.save_doc(tmp, "Design Notes", "# Intro\nLine one.\n", kind="md")
            did = created["id"]
            self.assertEqual(created["kind"], "md")

            listed = docs_canvas.list_docs(tmp)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["id"], did)

            def fake_editor(model, system, prompt):
                return "```md\n# Intro\nLine one updated.\nLine two.\n```"

            prop = docs_canvas.propose_edit(tmp, did, "Update line one", model="assist", caller=fake_editor)
            self.assertTrue(prop["ok"])
            self.assertTrue(prop["changed"])
            self.assertIn("-Line one.", prop["diff"])
            self.assertIn("+Line one updated.", prop["diff"])

            # Proposal must NOT mutate saved document until explicitly applied
            unchanged = docs_canvas.get_doc(tmp, did)
            self.assertEqual(unchanged["content"], "# Intro\nLine one.\n")

            # Apply update and verify .prev backup exists
            docs_canvas.save_doc(tmp, "Design Notes", prop["proposed"], kind="md", doc_id=did)
            updated = docs_canvas.get_doc(tmp, did)
            self.assertIn("Line one updated.", updated["content"])

            deleted = docs_canvas.delete_doc(tmp, did)
            self.assertTrue(deleted["ok"])
            self.assertEqual(docs_canvas.list_docs(tmp), [])

    def test_rejects_invalid_kind_and_id(self):
        with tempfile.TemporaryDirectory(prefix="atlas-docs-bad-") as tmp:
            with self.assertRaises(ValueError):
                docs_canvas.save_doc(tmp, "Bad", "x", kind="exe")
            with self.assertRaises(ValueError):
                docs_canvas.get_doc(tmp, "../escape")


class DeepResearchTests(unittest.TestCase):
    def test_research_pipeline_cites_sources_and_persists(self):
        def fake_search(subq, k):
            return [
                {"title": "Source One", "url": "https://example.com/one"},
                {"title": "Source Two", "url": "https://example.com/two"},
            ][:k]

        def fake_fetch(url):
            return f"Detailed technical content fetched from {url}."

        def fake_call(model, prompt):
            if "Break the following research question" in prompt:
                return "1. quantization tradeoffs\n2. MoE VRAM memory"
            return "# Report\nKey finding supported by [1] and [2]."

        with tempfile.TemporaryDirectory(prefix="atlas-res-") as tmp:
            res = research_pipeline.run_research(
                "Compare Q4_K_M and IQ4_XS",
                mode="local",
                max_sources=4,
                data_dir=tmp,
                searcher=fake_search,
                fetcher=fake_fetch,
                caller=fake_call,
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["mode"], "local")
            self.assertEqual(len(res["sources"]), 2)
            self.assertIn("[1]", res["report_md"])
            self.assertIn("## Sources", res["report_md"])

            saved = research_pipeline.list_reports(tmp)
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["research_id"], res["research_id"])

    def test_blocks_private_ssrf_urls(self):
        self.assertFalse(research_pipeline._is_safe_public_url("http://127.0.0.1:8090/api/state"))
        self.assertFalse(research_pipeline._is_safe_public_url("http://localhost:8080/v1/models"))
        self.assertFalse(research_pipeline._is_safe_public_url("http://192.168.1.10/secret"))
        self.assertFalse(research_pipeline._is_safe_public_url("file:///etc/passwd"))


class ModelCookbookTests(unittest.TestCase):
    def test_hardware_fit_classification_and_no_personal_paths(self):
        small_gpu = {"gpu_name": "RTX 4060", "vram_gb": 8.0, "ram_gb": 16.0, "cpu_count": 8}
        big_gpu = {"gpu_name": "RTX 4090", "vram_gb": 24.0, "ram_gb": 64.0, "cpu_count": 16}

        with tempfile.TemporaryDirectory(prefix="atlas-cb-") as tmp:
            rec_small = model_cookbook.recommendations(
                tmp, tmp, hardware=small_gpu, installed_names=["qwen2.5-coder-7b-instruct-q4_k_m.gguf"], peers=[]
            )
            by_id_small = {r["id"]: r for r in rec_small["recipes"]}
            self.assertEqual(by_id_small["qwen2.5-coder-7b-q4"]["fit"], "fits_vram")
            self.assertTrue(by_id_small["qwen2.5-coder-7b-q4"]["installed"])
            self.assertEqual(by_id_small["gemma3-27b-q4"]["fit"], "too_large")

            rec_big = model_cookbook.recommendations(
                tmp, tmp, hardware=big_gpu, installed_names=[], peers=[{"name": "Rig2", "models": ["mentor"]}]
            )
            by_id_big = {r["id"]: r for r in rec_big["recipes"]}
            self.assertEqual(by_id_big["gemma3-27b-q4"]["fit"], "lan_peer")
            self.assertEqual(by_id_big["qwen3-14b-q4"]["fit"], "fits_vram")

            for r in rec_small["recipes"]:
                self.assertIn("{models}", r["hf_cmd"])
                self.assertNotIn("C:\\Users\\", r["hf_cmd"])


class GovernedSkillsRegistryTests(unittest.TestCase):
    def test_skill_crud_governance_promotion_and_refinement_diff(self):
        tiers = {"read_file": "read", "write_file": "write"}
        with tempfile.TemporaryDirectory(prefix="atlas-sk-") as tmp:
            # Declares "read" but references a write tool -> must auto-promote to "write"
            sk = skills_registry.save_skill(
                tmp,
                "safe-refactor",
                name="Safe Refactor",
                description="Refactors modules cleanly",
                body="1. Inspect code.\n2. Apply minimal patch.",
                tier="read",
                enabled=True,
                allowed_tools=["read_file", "write_file"],
                tool_tiers=tiers,
            )
            self.assertEqual(sk["tier"], "read")
            self.assertEqual(sk["effective_tier"], "write")
            self.assertTrue(sk["requires_approval"])
            self.assertIn("write_file", sk["governance"]["promoted_by_tools"])

            # Pure read skill stays read
            ro = skills_registry.save_skill(
                tmp,
                "code-audit",
                name="Code Audit",
                body="Inspect for security bugs.",
                tier="read",
                allowed_tools=["read_file"],
                tool_tiers=tiers,
            )
            self.assertEqual(ro["effective_tier"], "read")
            self.assertFalse(ro["requires_approval"])

            prompt_block = skills_registry.active_skills_prompt(tmp, tool_tiers=tiers)
            self.assertIn("Safe Refactor [write]", prompt_block)
            self.assertIn("Code Audit [read]", prompt_block)

            # Refinement produces diff without mutating disk
            prop = skills_registry.refine_skill(
                tmp,
                "code-audit",
                "Add SQL injection checklist",
                caller=lambda m, p: "Inspect for security bugs.\nCheck for SQL injection.",
                tool_tiers=tiers,
            )
            self.assertTrue(prop["changed"])
            self.assertIn("+Check for SQL injection.", prop["diff"])
            self.assertNotIn("SQL injection", skills_registry.get_skill(tmp, "code-audit", tool_tiers=tiers)["body"])

            deleted = skills_registry.delete_skill(tmp, "safe-refactor")
            self.assertTrue(deleted["ok"])


class NewUiContractsTests(unittest.TestCase):
    def test_all_four_dialogs_and_slash_commands_present(self):
        html = HTML_PATH.read_text(encoding="utf-8")
        for needle in (
            'id="docsDlg"',
            'id="researchDlg"',
            'id="cookbookDlg"',
            'id="skillsRegDlg"',
            '"/docs"',
            '"/research"',
            '"/cookbook"',
            '"/skills-reg"',
        ):
            self.assertIn(needle, html)


if __name__ == "__main__":
    unittest.main()
