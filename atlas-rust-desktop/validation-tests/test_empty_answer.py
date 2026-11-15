import os, sys, tempfile, unittest
os.environ["ATLAS_OBSERVABILITY_DB"] = os.path.join(tempfile.mkdtemp(), "o.sqlite3")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src-tauri", "resources", "atlas"))
import cloud_llm
import swarm_run


class EmptyAnswer(unittest.TestCase):
    def test_local_empty_answer_is_retried_once_with_a_bigger_limit(self):
        limits = []
        def fake(prompt, temperature=0, max_tokens=0, model=None, **kw):
            limits.append(max_tokens)
            return "" if len(limits) == 1 else "A real answer."
        self.assertEqual(swarm_run._ask_local(fake, "p", "coder"), "A real answer.")
        self.assertEqual(limits, [900, 3000])

    def test_local_still_empty_after_retry_returns_empty(self):
        self.assertEqual(swarm_run._ask_local(lambda *a, **k: "  ", "p", "coder"), "")

    def test_local_good_answer_asks_only_once(self):
        calls = []
        swarm_run._ask_local(lambda *a, **k: calls.append(1) or "ok", "p", "coder")
        self.assertEqual(len(calls), 1)

    def test_gemini_flash_turns_thinking_off(self):
        old = cloud_llm.GEMINI_MODEL
        try:
            cloud_llm.GEMINI_MODEL = "gemini-2.5-flash"
            self.assertEqual(cloud_llm._gemini_config(0.3, 900)["thinkingConfig"], {"thinkingBudget": 0})
            cloud_llm.GEMINI_MODEL = "gemini-2.5-pro"
            self.assertNotIn("thinkingConfig", cloud_llm._gemini_config(0.3, 900))
        finally:
            cloud_llm.GEMINI_MODEL = old

    def test_gemini_empty_answer_says_why(self):
        self.assertIn("MAX_TOKENS", cloud_llm._gemini_why({"candidates": [{"finishReason": "MAX_TOKENS"}]}))
        self.assertIn("SAFETY", cloud_llm._gemini_why({"promptFeedback": {"blockReason": "SAFETY"}}))
        self.assertEqual(cloud_llm._gemini_why({}), "")

    def test_bot_prompt_carries_project_facts(self):
        self.assertIn("Atlas Chat", swarm_run.PROJECT_CONTEXT)


if __name__ == "__main__":
    unittest.main()
