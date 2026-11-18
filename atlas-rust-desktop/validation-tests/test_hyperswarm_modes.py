import no_real_keys  # noqa: F401
import os
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "src-tauri" / "resources" / "atlas"
sys.path.insert(0, str(APP))

import atlas_observability as OPS  # noqa: E402
import cloud_llm  # noqa: E402
import swarm_run  # noqa: E402


class HyperswarmModesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_db = OPS.DB_PATH
        OPS.DB_PATH = Path(tempfile.mkdtemp(prefix="atlas-hyperswarm-")) / "obs.sqlite3"

    @classmethod
    def tearDownClass(cls):
        OPS.DB_PATH = cls._old_db

    def test_providers_and_free_tiers_defined(self):
        self.assertIn("gemini", cloud_llm.PROVIDERS)
        self.assertIn("groq", cloud_llm.PROVIDERS)
        self.assertIn("cerebras", cloud_llm.PROVIDERS)
        self.assertIn("openrouter", cloud_llm.PROVIDERS)
        self.assertIn("mistral", cloud_llm.PROVIDERS)
        self.assertIn("github", cloud_llm.PROVIDERS)
        self.assertIn("abliterated", cloud_llm.PROVIDERS)
        self.assertEqual(cloud_llm.model_name("groq"), "llama-3.3-70b-versatile")
        self.assertEqual(cloud_llm.model_name("cerebras"), "llama-3.3-70b")
        self.assertEqual(cloud_llm.model_name("github"), "gpt-4o-mini")

    def test_local_mode_runs_offline(self):
        prompts = []
        def stub_llm(p, *a, **k):
            prompts.append(p)
            return "LOCAL-ANSWER"

        run = swarm_run.start("build offline engine", [{"agent": "10x: SDE", "task": "write code"}],
                              call_llm=stub_llm, mode="local")
        self.assertEqual(run["mode"], "local")
        self.assertFalse(run["pipeline"])
        conv = run["steps"][0]["conversation_id"]
        for _ in range(50):
            if OPS.swarm_log(conv)["done"]:
                break
            import time
            time.sleep(0.05)
        log = OPS.swarm_log(conv)
        self.assertTrue(log["done"])
        self.assertEqual(log["status"], "completed")

    def test_abliterated_mode_injects_unrestricted_directive(self):
        prompts = []
        def stub_llm(p, *a, **k):
            prompts.append(p)
            return "ABLITERATED-ANSWER"

        run = swarm_run.start("audit security constraints", [{"agent": "10x: Senior Engineer", "task": "review"}],
                              call_llm=stub_llm, mode="abliterated")
        self.assertEqual(run["mode"], "abliterated")
        conv = run["steps"][0]["conversation_id"]
        for _ in range(50):
            if OPS.swarm_log(conv)["done"]:
                break
            import time
            time.sleep(0.05)
        self.assertTrue(any("[MODE: ABLITERATED / UNRESTRICTED]" in p for p in prompts))

    def test_hyper_mode_preserves_pipeline_support(self):
        old_key = os.environ.get("GEMINI_API_KEY")
        try:
            os.environ["GEMINI_API_KEY"] = "fake-key"
            self.assertTrue(swarm_run.pipeline_wanted("hyper"))
        finally:
            if old_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = old_key


if __name__ == "__main__":
    unittest.main()
