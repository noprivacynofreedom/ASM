import no_real_keys  # noqa: F401  (must run before cloud_llm is imported)
"""Tests for the cloud model picker catalog and chat_completion routing."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "src-tauri" / "resources" / "atlas"
sys.path.insert(0, str(APP))
import cloud_llm  # noqa: E402

SECRET = "TEST-CLOUD-KEY-999"
SEEN = []


def _fake_post(url, headers, payload, timeout):
    SEEN.append({"url": url, "headers": dict(headers), "body": payload})
    if "anthropic" in url:
        return {"content": [{"type": "text", "text": "ANTHROPIC-OK"}]}
    if "generativelanguage" in url or "gemini" in url:
        return {"candidates": [{"content": {"parts": [{"text": "GEMINI-OK"}]}}]}
    return {"choices": [{"message": {"content": f"OPENAI-COMPAT-OK:{payload.get('model')}"}}]}


class CloudPickerTests(unittest.TestCase):
    def setUp(self):
        SEEN.clear()
        for k in no_real_keys._KEY_NAMES:
            os.environ.pop(k, None)

    def tearDown(self):
        for k in no_real_keys._KEY_NAMES:
            os.environ.pop(k, None)

    def test_picker_models_list_free_and_paid_without_leaking_keys(self):
        os.environ["GROQ_API_KEY"] = SECRET
        os.environ["XAI_API_KEY"] = SECRET
        items = cloud_llm.picker_models()
        by_id = {m["id"]: m for m in items}
        for expected in (
            "cloud:gemini", "cloud:openrouter-free", "cloud:qwen-coder-free",
            "cloud:groq", "cloud:cerebras", "cloud:mistral", "cloud:github",
            "cloud:deepseek", "cloud:grok", "cloud:openai", "cloud:anthropic",
        ):
            self.assertIn(expected, by_id)
        self.assertTrue(by_id["cloud:groq"]["ready"])
        self.assertTrue(by_id["cloud:grok"]["ready"])
        self.assertFalse(by_id["cloud:openai"]["ready"])
        self.assertNotIn(SECRET, json.dumps(items))

    def test_chat_completion_routes_groq_grok_gemini_and_anthropic(self):
        os.environ["GROQ_API_KEY"] = SECRET
        os.environ["GROK_API_KEY"] = SECRET
        os.environ["ANTHROPIC_API_KEY"] = SECRET
        os.environ["GEMINI_API_KEY"] = SECRET

        with mock.patch.object(cloud_llm, "_post", side_effect=_fake_post):
            comp, machine = cloud_llm.chat_completion({
                "model": "cloud:groq",
                "messages": [{"role": "user", "content": "hi"}],
            })
            self.assertIn("OPENAI-COMPAT-OK:", comp["choices"][0]["message"]["content"])
            self.assertIn("GROQ", machine)

            comp2, machine2 = cloud_llm.chat_completion({
                "model": "cloud:grok",
                "messages": [{"role": "user", "content": "hi"}],
            })
            self.assertIn("OPENAI-COMPAT-OK:", comp2["choices"][0]["message"]["content"])
            self.assertIn("GROK", machine2)

            comp3, machine3 = cloud_llm.chat_completion({
                "model": "cloud:anthropic",
                "messages": [{"role": "system", "content": "be concise"}, {"role": "user", "content": "hi"}],
            })
            self.assertEqual(comp3["choices"][0]["message"]["content"], "ANTHROPIC-OK")
            self.assertIn("ANTHROPIC", machine3)

            comp4, machine4 = cloud_llm.chat_completion({
                "model": "cloud:gemini",
                "messages": [{"role": "user", "content": "hi"}],
            })
            self.assertEqual(comp4["choices"][0]["message"]["content"], "GEMINI-OK")
            self.assertIn("GEMINI", machine4)

    def test_missing_key_raises_401_with_env_name(self):
        with self.assertRaises(cloud_llm.CloudError) as ctx:
            cloud_llm.chat_completion({"model": "cloud:groq", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(ctx.exception.code, 401)
        self.assertIn("GROQ_API_KEY", str(ctx.exception))

    def test_index_html_groups_local_and_cloud_in_model_picker(self):
        html = (APP / "index.html").read_text(encoding="utf-8")
        self.assertIn("function fillModelOptions(", html)
        self.assertIn('localGroup.label = "LOCAL (THIS PC)"', html)
        self.assertIn('cloudGroup.label = "CLOUD (TEXT LEAVES THIS PC)"', html)
        self.assertIn('fetch("/api/cloud/models"', html)


if __name__ == "__main__":
    unittest.main()
