"""A fake llama-swap + llama-server for context engine tests. Standard library only.

Run: python fake_llama_swap.py <port> [n_ctx]
It speaks the endpoints Atlas uses: /v1/models, /running, /upstream/<m>/props, /upstream/<m>/apply-template,
/upstream/<m>/tokenize, /v1/chat/completions (stream and non-stream, with usage and timings).
Its tokenizer is 1 token per 4 characters, so tests can check counts exactly. GET /_last returns the last chat request.
"""
import json
import math
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

N_CTX = 8192
LAST = {"chat": None, "count": 0}
LOCK = threading.Lock()


def template(messages):
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            content = "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") == "text")
        out.append(f"<|{m.get('role', 'user')}|>{content or ''}<|end|>")
    return "".join(out) + "<|assistant|>"


def ntok(text):
    return max(1, math.ceil(len(text) / 4))


def answer_for(req):
    msgs = req.get("messages") or []
    system = msgs[0].get("content", "") if msgs and msgs[0].get("role") == "system" else ""
    system = system if isinstance(system, str) else json.dumps(system)
    flags = []
    if "ATLAS MEMORY" in system:
        flags.append("memory=yes")
    if "ATLAS RETRIEVED KNOWLEDGE" in system:
        flags.append("knowledge=yes")
    if "EARLIER CONVERSATION SUMMARY" in system:
        flags.append("summary=yes")
    last = next((m.get("content") for m in reversed(msgs) if m.get("role") == "user"), "")
    last = last if isinstance(last, str) else "[parts]"
    return f"Reply to: {last[:60]} | sent {len(msgs)} messages | {' '.join(flags) or 'plain'}"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path == "/v1/models":
            return self._json(200, {"data": [{"id": "assist"}, {"id": "coder"}]})
        if self.path == "/running":
            return self._json(200, {"running": [{"model": "assist", "state": "ready"}]})
        if self.path.endswith("/props") and self.path.startswith("/upstream/"):
            return self._json(200, {"default_generation_settings": {"n_ctx": N_CTX}, "modalities": {"vision": False}})
        if self.path == "/_last":
            with LOCK:
                return self._json(200, LAST)
        if self.path == "/health":
            return self._json(200, {"status": "ok"})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        req = self._body()
        if self.path.endswith("/apply-template"):
            return self._json(200, {"prompt": template(req.get("messages") or [])})
        if self.path.endswith("/tokenize"):
            return self._json(200, {"tokens": list(range(ntok(str(req.get("content", "")))))})
        if self.path == "/v1/embeddings":
            return self._json(404, {"error": "no embeddings"})
        if self.path != "/v1/chat/completions":
            return self._json(404, {"error": "not found"})
        with LOCK:
            LAST["chat"] = req
            LAST["count"] += 1
        prompt_tokens = ntok(template(req.get("messages") or []))
        if not req.get("stream"):
            text = "SUMMARY: the user and assistant discussed earlier topics." if "compress a conversation" in json.dumps(req) else answer_for(req)
            return self._json(200, {"id": "x", "object": "chat.completion", "model": req.get("model"),
                                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                                    "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": ntok(text), "total_tokens": prompt_tokens + ntok(text)}})
        text = answer_for(req)
        words = text.split(" ")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for i, w in enumerate(words):
            chunk = {"choices": [{"index": 0, "delta": {"content": (" " if i else "") + w}}]}
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.flush()
        cached = min(prompt_tokens - 1, 100)
        final = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "timings": {"prompt_n": prompt_tokens - cached, "cache_n": cached, "predicted_n": len(words), "predicted_per_second": 50.0}}
        if (req.get("stream_options") or {}).get("include_usage"):
            final["usage"] = {"prompt_tokens": prompt_tokens, "completion_tokens": len(words), "total_tokens": prompt_tokens + len(words)}
        self.wfile.write(("data: " + json.dumps(final) + "\n\ndata: [DONE]\n\n").encode())
        self.wfile.flush()


def serve(port, n_ctx=8192):
    global N_CTX
    N_CTX = n_ctx
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    serve(int(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 8192)
    threading.Event().wait()
