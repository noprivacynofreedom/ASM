import json, os, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA = tempfile.mkdtemp()
os.environ["ATLAS_DATA_DIR"] = DATA
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src-tauri", "resources", "atlas"))
import compute_peers as CP
import llm

SEEN = []

class FakePeer(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        SEEN.append(("GET", self.path, self.headers.get("Authorization")))
        if self.path == "/v1/models":
            return self._json(200, {"data": [{"id": "laptop-7b"}, {"id": "laptop-14b"}]})
        self._json(200, {"ok": True})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        SEEN.append(("POST", self.path, self.headers.get("Authorization")))
        self._json(200, {"choices": [{"message": {"content": "hello from laptop:" + body["model"]}}]})

def write_settings(**kw):
    with open(os.path.join(DATA, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(kw, f)

class ComputePeers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakePeer)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def setUp(self): SEEN.clear(); write_settings()

    def test_rejects_public_and_bad_urls(self):
        for url in ("http://8.8.8.8:8080", "https://192.168.1.5:8080", "http://user:pw@192.168.1.5",
                    "http://192.168.1.5/path", ""):
            self.assertTrue(CP.parse_url(url)[2], url)
    def test_accepts_lan_and_defaults_port(self):
        self.assertEqual(CP.parse_url("http://192.168.1.50")[:2], ("192.168.1.50", 8080))
        self.assertEqual(CP.parse_url("10.0.0.7:9000")[:2], ("10.0.0.7", 9000))
    def test_public_allowed_only_when_user_turns_it_on(self):
        self.assertTrue(CP.parse_url("http://8.8.8.8:8080")[2])
        write_settings(compute_allow_public=True)
        self.assertEqual(CP.parse_url("http://8.8.8.8:8080")[2], "")

    def test_test_url_online_and_offline(self):
        ok = CP.test_url(f"http://127.0.0.1:{self.port}", "Laptop")
        self.assertTrue(ok["online"]); self.assertEqual(ok["message"], "Laptop is online. It has 2 models.")
        down = CP.test_url("http://127.0.0.1:1", "Laptop")
        self.assertFalse(down["online"]); self.assertIn("offline", down["message"])
        self.assertFalse(CP.test_url("http://8.8.8.8:8080")["ok"])

    def test_save_route_and_remove(self):
        saved = CP.save_peer("Laptop", f"http://127.0.0.1:{self.port}")
        self.assertEqual(saved["models"], ["laptop-7b", "laptop-14b"])  # learned from the peer
        host, port, peer = CP.route("laptop-7b")
        self.assertEqual((host, port, peer["name"]), ("127.0.0.1", self.port, "Laptop"))
        self.assertEqual(CP.route("coder"), (None, None, None))  # local stays the default
        status = CP.peers_status()
        self.assertTrue(status["peers"][0]["online"])
        self.assertTrue(CP.remove_peer("Laptop")["removed"])
        self.assertEqual(CP.route("laptop-7b"), (None, None, None))

    def test_bad_settings_entry_is_skipped_and_reported(self):
        write_settings(compute_peers=[{"name": "Evil", "url": "http://8.8.8.8:8080", "models": ["x"]}])
        peers, problems = CP.load_peers()
        self.assertEqual(peers, []); self.assertEqual(len(problems), 1)

    def test_llm_call_goes_to_peer_only_for_its_alias(self):
        write_settings(compute_peers=[{"name": "Laptop", "url": f"http://127.0.0.1:{self.port}",
                                       "models": ["laptop-7b"], "api_key": "peerkey"}])
        self.assertEqual(llm.call_llm("hi", model="laptop-7b"), "hello from laptop:laptop-7b")
        post = [s for s in SEEN if s[0] == "POST"]
        self.assertEqual(post[0][2], "Bearer peerkey")

    def test_peer_never_gets_the_local_key(self):
        write_settings(compute_peers=[{"name": "Laptop", "url": f"http://127.0.0.1:{self.port}", "models": ["a"]}])
        os.environ["ATLAS_UPSTREAM_API_KEY"] = "localkey"
        try:
            import upstream_auth; upstream_auth._CACHE = None
            self.assertNotIn("Authorization", CP.headers_for("127.0.0.1", self.port, {}))
            self.assertEqual(CP.headers_for("127.0.0.1", 59999, {})["Authorization"], "Bearer localkey")
        finally:
            os.environ.pop("ATLAS_UPSTREAM_API_KEY"); upstream_auth._CACHE = None

    def test_unload_all(self):
        write_settings(compute_peers=[{"name": "Laptop", "url": f"http://127.0.0.1:{self.port}", "models": ["a"]}])
        self.assertEqual(CP.unload_all(), 1)
        self.assertIn(("GET", "/unload", None), SEEN)

if __name__ == "__main__":
    unittest.main()
