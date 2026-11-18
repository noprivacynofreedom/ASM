import no_real_keys  # noqa: F401  (must run before cloud_llm is imported)
"""Gemini retry and model fallback in cloud_llm. Uses a local stub server: no real network, no real keys."""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "src-tauri" / "resources" / "atlas"
sys.path.insert(0, str(APP))
import cloud_llm  # noqa: E402

SECRET = "SECRET-KEY-456"
import time  # noqa: E402
SLOW = {}  # model name -> how many first requests should stall (sleep) before answering
SEEN = []  # model names, in the order they were asked
PLAN = {}  # model name -> list of HTTP codes to answer with, then 200


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        model = self.path.rsplit("/", 1)[-1].split("?")[0]
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        SEEN.append((model, "thinkingConfig" in body.get("generationConfig", {})))
        if SLOW.get(model, 0) > 0:
            SLOW[model] -= 1
            time.sleep(1.2)  # longer than the attempt limit set in the test: the client gives up
            return
        codes = PLAN.get(model, [])
        code = codes.pop(0) if codes else 200
        if code != 200:
            self.send_response(code)
            self.end_headers()
            return
        raw = json.dumps({"candidates": [{"content": {"parts": [{"text": "ANSWER-FROM-" + model}]}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


class CloudRetry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        os.environ["ATLAS_GEMINI_URL"] = f"http://127.0.0.1:{cls.srv.server_address[1]}/" + "{model}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        os.environ.pop("ATLAS_GEMINI_URL", None)

    def setUp(self):
        SEEN.clear()
        PLAN.clear()
        SLOW.clear()
        self._lim = (cloud_llm.GEMINI_ATTEMPT_SECONDS, cloud_llm.GEMINI_BUDGET_SECONDS)
        self.addCleanup(lambda: setattr(cloud_llm, "GEMINI_ATTEMPT_SECONDS", self._lim[0]) or setattr(cloud_llm, "GEMINI_BUDGET_SECONDS", self._lim[1]))
        self._old = (cloud_llm.GEMINI_MODEL, cloud_llm.RETRY_WAITS, os.environ.get("GEMINI_API_KEY"))
        cloud_llm.GEMINI_MODEL = "dead,busy,good"
        cloud_llm.RETRY_WAITS = (0, 0)  # no real waiting in tests
        os.environ["GEMINI_API_KEY"] = SECRET
        self.addCleanup(self._restore)

    def _restore(self):
        cloud_llm.GEMINI_MODEL, cloud_llm.RETRY_WAITS, key = self._old
        if key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = key

    def test_missing_model_moves_to_the_next_one(self):
        PLAN["dead"] = [404]
        self.assertEqual(cloud_llm.call("gemini", "hi"), "ANSWER-FROM-busy")
        self.assertEqual([m for m, _ in SEEN], ["dead", "busy"])  # one try on the dead model, no retries

    def test_busy_answer_is_retried_on_the_same_model(self):
        cloud_llm.GEMINI_MODEL = "busy,good"
        PLAN["busy"] = [503, 503]
        self.assertEqual(cloud_llm.call("gemini", "hi"), "ANSWER-FROM-busy")
        self.assertEqual([m for m, _ in SEEN], ["busy", "busy", "busy"])

    def test_model_that_stays_busy_gives_way_to_the_next(self):
        cloud_llm.GEMINI_MODEL = "busy,good"
        PLAN["busy"] = [503, 503, 503]
        self.assertEqual(cloud_llm.call("gemini", "hi"), "ANSWER-FROM-good")
        self.assertEqual([m for m, _ in SEEN], ["busy", "busy", "busy", "good"])

    def test_every_model_failing_names_them_and_hides_the_key(self):
        PLAN.update({"dead": [404], "busy": [404], "good": [404]})
        with self.assertRaises(RuntimeError) as ctx:
            cloud_llm.call("gemini", "hi")
        text = str(ctx.exception)
        self.assertIn("HTTP 404", text)
        self.assertIn("tried dead, busy, good", text)
        self.assertNotIn(SECRET, text)

    def test_refused_key_stops_at_once(self):
        PLAN["dead"] = [403]
        with self.assertRaises(RuntimeError):
            cloud_llm.call("gemini", "hi")
        self.assertEqual([m for m, _ in SEEN], ["dead"])

    def test_model_that_refuses_thinking_off_is_asked_again_without_it(self):
        cloud_llm.GEMINI_MODEL = "flash-x"
        PLAN["flash-x"] = [400]
        self.assertEqual(cloud_llm.call("gemini", "hi"), "ANSWER-FROM-flash-x")
        self.assertEqual(SEEN, [("flash-x", True), ("flash-x", False)])

    def test_cloud_proxy_setting_routes_the_call_through_the_proxy(self):
        # The Gemini URL points at a host that does not exist; only the stub "proxy" can answer.
        port = self.srv.server_address[1]
        old = os.environ.get("ATLAS_GEMINI_URL")
        os.environ["ATLAS_GEMINI_URL"] = "http://gemini.invalid/{model}"
        os.environ["ATLAS_CLOUD_PROXY"] = f"http://127.0.0.1:{port}"
        cloud_llm.GEMINI_MODEL = "good"
        try:
            self.assertEqual(cloud_llm.call("gemini", "hi"), "ANSWER-FROM-good")
            os.environ.pop("ATLAS_CLOUD_PROXY")  # without it the call cannot reach the fake host
            with self.assertRaises(RuntimeError) as ctx:
                cloud_llm.call("gemini", "hi")
            self.assertIn("ATLAS_CLOUD_PROXY", str(ctx.exception))  # the log tells you what to set
        finally:
            os.environ.pop("ATLAS_CLOUD_PROXY", None)
            os.environ["ATLAS_GEMINI_URL"] = old

    def test_stalled_connection_is_dropped_and_tried_again(self):
        cloud_llm.GEMINI_MODEL = "slow"
        cloud_llm.GEMINI_ATTEMPT_SECONDS = 0.4
        SLOW["slow"] = 1  # first try stalls, second answers
        self.assertEqual(cloud_llm.call("gemini", "hi"), "ANSWER-FROM-slow")
        self.assertEqual([m for m, _ in SEEN], ["slow", "slow"])  # the first request stalled and was dropped; the retry answered

    def test_a_dead_network_stops_at_the_time_budget(self):
        cloud_llm.GEMINI_MODEL = "slow,good"
        cloud_llm.GEMINI_ATTEMPT_SECONDS = 0.3
        cloud_llm.GEMINI_BUDGET_SECONDS = 1.5
        SLOW["slow"] = 99
        started = time.monotonic()
        with self.assertRaises(RuntimeError) as ctx:
            cloud_llm.call("gemini", "hi")
        self.assertLess(time.monotonic() - started, 4)  # not minutes
        self.assertIn("not reachable", str(ctx.exception))
        self.assertIn("tried slow)", str(ctx.exception))  # names what was really tried, not the whole list
        self.assertNotIn("ATLAS_CLOUD_PROXY", str(ctx.exception))  # a timeout is not proof of a missing proxy
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_single_model_name_still_works(self):
        cloud_llm.GEMINI_MODEL = "good"
        self.assertEqual(cloud_llm.call("gemini", "hi"), "ANSWER-FROM-good")


if __name__ == "__main__":
    unittest.main()
