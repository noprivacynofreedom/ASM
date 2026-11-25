import no_real_keys  # noqa: F401  (must run before cloud_llm is imported)
"""Tests for Vertex AI provider, dynamic live-provider switching, Cloud Keys settings store, and parallel swarm offload."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "src-tauri" / "resources" / "atlas"
sys.path.insert(0, str(APP))
import atlas_observability as OPS  # noqa: E402
import cloud_llm  # noqa: E402
import swarm_run  # noqa: E402

SEEN = []
STATE = {"fail_paths": set(), "delay": 0.0}


class MultiProviderStub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        SEEN.append({
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "gkey": self.headers.get("x-goog-api-key"),
            "body": body,
        })
        if STATE["delay"]:
            time.sleep(STATE["delay"])
        for fp in STATE["fail_paths"]:
            if fp in self.path:
                self.send_response(500)
                self.end_headers()
                return
        if "vertex" in self.path:
            out = {"candidates": [{"content": {"parts": [{"text": "VERTEX-ANSWER"}]}}]}
        elif "gemini" in self.path:
            out = {"candidates": [{"content": {"parts": [{"text": "GEMINI-ANSWER"}]}}]}
        elif "groq" in self.path:
            out = {"choices": [{"message": {"content": "GROQ-ANSWER"}}]}
        else:
            out = {"choices": [{"message": {"content": "OPENROUTER-ANSWER"}}]}
        raw = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def local_llm(prompt, temperature=0, max_tokens=0, model=None):
    return "LOCAL-ANSWER"


class VertexDynamicCloudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_db = OPS.DB_PATH
        OPS.DB_PATH = Path(tempfile.mkdtemp(prefix="atlas-vertex-cloud-")) / "obs.sqlite3"
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), MultiProviderStub)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        OPS.DB_PATH = cls._old_db

    def setUp(self):
        self._old_waits = cloud_llm.RETRY_WAITS
        cloud_llm.RETRY_WAITS = (0, 0)
        self.addCleanup(setattr, cloud_llm, "RETRY_WAITS", self._old_waits)
        self._tmp = tempfile.mkdtemp(prefix="atlas-keys-")
        self._keys_file = os.path.join(self._tmp, "cloud_keys.json")
        env_keys = (
            "GEMINI_API_KEY", "VERTEX_API_KEY", "GOOGLE_CLOUD_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
            "ATLAS_GEMINI_URL", "ATLAS_VERTEX_URL", "ATLAS_GROQ_URL", "ATLAS_OPENROUTER_URL",
            "ATLAS_CLOUD_SWARM", "ATLAS_SWARM_CLOUD_OFFLOAD", "ATLAS_CLOUD_KEYS_FILE",
        )
        self._saved = {k: os.environ.get(k) for k in env_keys}
        self.addCleanup(self._restore)
        for k in env_keys:
            os.environ.pop(k, None)
        os.environ["ATLAS_CLOUD_KEYS_FILE"] = self._keys_file
        os.environ["ATLAS_GEMINI_URL"] = self.base + "/gemini/{model}"
        os.environ["ATLAS_VERTEX_URL"] = self.base + "/vertex/{model}"
        os.environ["ATLAS_GROQ_URL"] = self.base + "/groq"
        os.environ["ATLAS_OPENROUTER_URL"] = self.base + "/openrouter"
        SEEN.clear()
        STATE["fail_paths"] = set()
        STATE["delay"] = 0.0
        cloud_llm.reset_health()

    def _restore(self):
        cloud_llm.reset_health()
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_vertex_express_mode_works_without_gemini_key(self):
        os.environ["VERTEX_API_KEY"] = "VTX-SECRET-999"
        text, prov, _model = cloud_llm.call_dynamic("hello", preferred="gemini")
        self.assertEqual(text, "VERTEX-ANSWER")
        self.assertEqual(prov, "vertex")
        self.assertEqual(len(SEEN), 1)
        self.assertTrue(SEEN[0]["path"].startswith("/vertex/"))
        self.assertEqual(SEEN[0]["gkey"], "VTX-SECRET-999")
        self.assertTrue(cloud_llm.is_cloud_model("cloud:vertex"))
        self.assertTrue(cloud_llm.is_cloud_model("cloud:auto"))

    def test_dynamic_failover_from_down_gemini_to_live_vertex_and_cooldown_sticks(self):
        os.environ["GEMINI_API_KEY"] = "GEM-SECRET-111"
        os.environ["VERTEX_API_KEY"] = "VTX-SECRET-222"
        STATE["fail_paths"] = {"/gemini/"}
        text, prov, _m = cloud_llm.call_dynamic("first call", preferred="gemini")
        self.assertEqual(text, "VERTEX-ANSWER")
        self.assertEqual(prov, "vertex")
        # Gemini is now in cooldown and Vertex is live: second call must go straight to Vertex.
        SEEN.clear()
        text2, prov2, _m2 = cloud_llm.call_dynamic("second call", preferred="gemini")
        self.assertEqual(text2, "VERTEX-ANSWER")
        self.assertEqual(prov2, "vertex")
        self.assertEqual(len(SEEN), 1)
        self.assertTrue(SEEN[0]["path"].startswith("/vertex/"))

    def test_settings_keys_panel_save_mask_probe_and_clear(self):
        view = cloud_llm.save_keys({
            "cloud_enabled": True,
            "swarm_offload": True,
            "providers": {
                "vertex": {"api_key": "VTX-PANEL-SECRET-1234", "enabled": True},
                "groq": {"api_key": "GRQ-PANEL-SECRET-5678", "enabled": True},
            },
        })
        self.assertTrue(view["swarm_offload"])
        self.assertEqual(view["ready_count"], 2)
        dumped = json.dumps(view)
        self.assertNotIn("VTX-PANEL-SECRET-1234", dumped)
        self.assertNotIn("GRQ-PANEL-SECRET-5678", dumped)
        v_row = next(p for p in view["providers"] if p["id"] == "vertex")
        self.assertEqual(v_row["key_source"], "settings")
        self.assertEqual(v_row["key_hint"], "••••1234")

        # Probe live keys
        probed = cloud_llm.probe()
        self.assertEqual(probed["live_count"], 2)
        self.assertTrue(probed["results"]["vertex"]["ok"])
        self.assertTrue(probed["results"]["groq"]["ok"])

        # Reject invalid URL
        with self.assertRaises(ValueError):
            cloud_llm.save_keys({"providers": {"vertex": {"url": "ftp://bad.example"}}})

        # Clear saved key
        cleared = cloud_llm.save_keys({"providers": {"vertex": {"clear_key": True}}})
        v_after = next(p for p in cleared["providers"] if p["id"] == "vertex")
        self.assertFalse(v_after["key_set"])

    def test_swarm_offload_spreads_work_across_live_keys_without_leaking_secrets(self):
        cloud_llm.save_keys({
            "cloud_enabled": True,
            "swarm_offload": True,
            "providers": {
                "vertex": {"api_key": "VTX-SWARM-SECRET-AAA", "enabled": True},
                "groq": {"api_key": "GRQ-SWARM-SECRET-BBB", "enabled": True},
                "openrouter": {"api_key": "OR-SWARM-SECRET-CCC", "enabled": True},
            },
        })
        cloud_llm.probe()
        SEEN.clear()

        run = swarm_run.start(
            "speed up swarm",
            [
                {"agent": "10x: SDE", "task": "write module A"},
                {"agent": "10x: QA Engineer", "task": "write tests B"},
                {"agent": "10x: CTO", "task": "review architecture C"},
            ],
            call_llm=local_llm,
        )
        convs = [s["conversation_id"] for s in run["steps"]]
        for _ in range(100):
            done = {e["conversation_id"] for e in OPS.events(0, 2000) if e.get("kind") in ("swarm.done", "swarm.failed")}
            if all(c in done for c in convs):
                break
            time.sleep(0.05)

        evs = OPS.events(0, 5000)
        dumped_evs = json.dumps(evs)
        self.assertNotIn("VTX-SWARM-SECRET-AAA", dumped_evs)
        self.assertNotIn("GRQ-SWARM-SECRET-BBB", dumped_evs)
        self.assertNotIn("OR-SWARM-SECRET-CCC", dumped_evs)
        # All 3 bots should have been answered by cloud providers (not local) across multiple providers.
        paths = [s["path"] for s in SEEN]
        self.assertEqual(len(paths), 3)
        self.assertGreaterEqual(len({p.split("/")[1] for p in paths}), 2)


if __name__ == "__main__":
    unittest.main()
