import no_real_keys  # noqa: F401  (must run before cloud_llm is imported)
import os, sys, tempfile, unittest
os.environ["ATLAS_OBSERVABILITY_DB"] = os.path.join(tempfile.mkdtemp(), "o.sqlite3")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src-tauri", "resources", "atlas"))
import cloud_llm
import swarm_run


class EmptyAnswer(unittest.TestCase):
    def test_local_empty_answer_is_retried_once_with_a_bigger_limit(self):
        limits, thinks = [], []
        def fake(prompt, temperature=0, max_tokens=0, model=None, think=True, **kw):
            limits.append(max_tokens)
            thinks.append(think)
            return "" if len(limits) == 1 else "A real answer."
        self.assertEqual(swarm_run._ask_local(fake, "p", "coder"), "A real answer.")
        self.assertEqual(limits, [900, 3000])
        self.assertEqual(thinks, [True, False])  # the retry turns thinking off (mentor spent 3000 tokens thinking)

    def test_think_off_reaches_llama_cpp(self):
        import llm
        sent = {}
        old = llm._request
        llm._request = lambda path, payload=None, **k: sent.update(payload) or {"choices": [{"message": {"content": "ok"}}]}
        try:
            llm.call_llm("p", model="mentor", think=False)
            self.assertEqual(sent["chat_template_kwargs"], {"enable_thinking": False})
            sent.clear()
            llm.call_llm("p", model="mentor", think=True)
            self.assertNotIn("chat_template_kwargs", sent)
        finally:
            llm._request = old

    def test_background_calls_do_not_think_by_default(self):
        import config, llm
        sent = {}
        old, old_setting = llm._request, config.SETTINGS.pop("llm_think", None)
        llm._request = lambda path, payload=None, **k: sent.update(payload) or {"choices": [{"message": {"content": "ok"}}]}
        try:
            llm.call_llm("p", model="mentor")
            self.assertEqual(sent["chat_template_kwargs"], {"enable_thinking": False})
            sent.clear()
            config.SETTINGS["llm_think"] = True  # settings.json can turn thinking back on
            llm.call_llm("p", model="mentor")
            self.assertNotIn("chat_template_kwargs", sent)
        finally:
            llm._request = old
            config.SETTINGS.pop("llm_think", None)
            if old_setting is not None:
                config.SETTINGS["llm_think"] = old_setting

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
