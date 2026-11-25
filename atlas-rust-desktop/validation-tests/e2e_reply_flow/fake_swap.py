# Fake llama-swap. MODE file picks behaviour: ok | empty_once | empty_always | bad_once
import json, os, sys, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
D = sys.argv[2]; N = {"n": 0, "unload": 0}
def mode(): return open(os.path.join(D, "mode")).read().strip()
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        b = json.dumps({"data": [{"id": "coder", "status": {"value": "loaded"}}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n)
        if self.path == "/unload":
            N["unload"] += 1; open(os.path.join(D, "unloads"), "w").write(str(N["unload"]))
            self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"OK"); return
        N["n"] += 1; m = mode(); fail = (m == "empty_always") or (m in ("empty_once", "bad_once") and N["n"] == 1)
        if m == "bad_once" and fail:
            self.send_response(502); self.send_header("Content-Length", "0"); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        def w(o): self.wfile.write(b"data: " + (o if isinstance(o, bytes) else json.dumps(o).encode()) + b"\n\n"); self.wfile.flush()
        if fail:
            w({"choices": [{"delta": {}, "finish_reason": "stop"}], "timings": {}}); w(b"[DONE]"); return
        toks = ["Hello ", "from ", "the fake model."] if m != "slow" else ["tok%d " % i for i in range(8)]
        for t in toks:
            w({"choices": [{"delta": {"content": t}}]}); time.sleep(0.05 if m != "slow" else 1.0)
        w({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 4}, "timings": {"predicted_n": 4, "prompt_n": 5}}); w(b"[DONE]")
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
