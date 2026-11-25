"""One log line per upstream model request, so a slow reply shows WHERE the time went.

File: <data>/logs/chat-timing.jsonl. No message text, no file names, no personal data.
Fields: ts, request_id, n (request number inside one chat message), model, loaded_before,
prompt_n, cache_n, prompt_per_second, prompt_ms, ttft_s, total_s, wait_s, completion_n, finish.
wait_s = ttft_s minus prompt_ms: time spent waiting or loading BEFORE llama.cpp began to read the prompt
(model load, model swap, or another request holding the single slot).
Standard library only. Every function is safe: a logging error never breaks a chat.
"""
import json
import os
import threading
import time

_LOCK = threading.Lock()
_COUNTS = {}
_MAX_BYTES = 512 * 1024
_log_path = None


def configure(data_dir):
    global _log_path
    _log_path = os.path.join(data_dir, "logs", "chat-timing.jsonl")


def breakdown(request):
    """Size of each prompt part in chars (about 4 chars = 1 token): system, history, last user message, tools.
    Shows in the timing log which part makes a prompt big."""
    out = {"system": 0, "history": 0, "last_user": 0, "tools": 0, "msgs": 0}
    try:
        msgs = request.get("messages") or []
        out["msgs"] = len(msgs)
        for i, m in enumerate(msgs):
            c = m.get("content") if isinstance(m, dict) else ""
            n = len(c) if isinstance(c, str) else len(json.dumps(c, separators=(",", ":")))
            if isinstance(m, dict) and m.get("role") == "system":
                out["system"] += n
            else:
                out["history"] += n
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content")
                out["last_user"] = len(c) if isinstance(c, str) else len(json.dumps(c, separators=(",", ":")))
                break
        out["tools"] = len(json.dumps(request.get("tools") or [], separators=(",", ":")))
    except Exception:
        pass
    return out


def entry(request_id, model, t_start, t_first, t_end, completion, loaded_before=None, finish=None, parts=None):
    """Build one log row from the timestamps and the upstream completion (dict with timings/usage)."""
    comp = completion if isinstance(completion, dict) else {}
    timings = comp.get("timings") if isinstance(comp.get("timings"), dict) else {}
    usage = comp.get("usage") if isinstance(comp.get("usage"), dict) else {}
    ttft = (t_first - t_start) if t_first else None
    prompt_ms = timings.get("prompt_ms")
    wait = None
    if ttft is not None and isinstance(prompt_ms, (int, float)):
        wait = max(0.0, ttft - prompt_ms / 1000.0)
    n = _COUNTS.get(request_id or "-", 0) + 1
    _COUNTS[request_id or "-"] = n
    if len(_COUNTS) > 500:
        _COUNTS.clear()
    row = {
        "ts": int(time.time()), "request_id": request_id or "-", "n": n, "model": str(model or "")[:80],
        "loaded_before": loaded_before,
        "prompt_n": timings.get("prompt_n", usage.get("prompt_tokens")),
        "cache_n": timings.get("cache_n"),
        "prompt_per_second": _r(timings.get("prompt_per_second")),
        "prompt_ms": _r(prompt_ms),
        "ttft_s": _r(ttft), "total_s": _r(t_end - t_start), "wait_s": _r(wait),
        "completion_n": timings.get("predicted_n", usage.get("completion_tokens")),
        "finish": finish,
    }
    if parts:
        row["prompt_chars"] = parts
    ch = comp.get("choices")
    ch0 = ch[0] if isinstance(ch, list) and ch and isinstance(ch[0], dict) else {}
    msg = ch0.get("message") if isinstance(ch0.get("message"), dict) else {}
    row["finish_reason"] = ch0.get("finish_reason")
    row["answer_chars"] = len(msg.get("content") or "") if isinstance(msg.get("content"), str) else 0
    row["tool_calls"] = len(msg.get("tool_calls") or []) if isinstance(msg.get("tool_calls"), list) else 0
    row["reasoning_chars"] = comp.get("atlas_reasoning_chars", 0)
    # Per-phase seconds for the Action History card: wait (load/queue), prompt read, generation (thinking + answer).
    row["gen_s"] = _r(t_end - t_first) if t_first else None
    row["phases"] = {"wait_s": row["wait_s"], "prompt_s": _r(prompt_ms / 1000.0) if isinstance(prompt_ms, (int, float)) else None,
                     "generate_s": row["gen_s"], "thinking_only": bool(row["reasoning_chars"] and not row["answer_chars"] and not row["tool_calls"])}
    return row


def _r(v):
    return round(v, 2) if isinstance(v, (int, float)) else None


def write(row):
    if not _log_path:
        return
    try:
        with _LOCK:
            os.makedirs(os.path.dirname(_log_path), exist_ok=True)
            if os.path.exists(_log_path) and os.path.getsize(_log_path) > _MAX_BYTES:
                keep = open(_log_path, "rb").read()[-_MAX_BYTES // 2:]
                keep = keep[keep.find(b"\n") + 1:]
                with open(_log_path, "wb") as f:
                    f.write(keep)
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
    except Exception:
        pass


def recent(limit=20):
    if not _log_path or not os.path.exists(_log_path):
        return []
    try:
        with _LOCK:
            lines = open(_log_path, "rb").read()[-200000:].decode("utf-8", "replace").splitlines()
    except Exception:
        return []
    out = []
    for line in lines[-max(1, min(int(limit), 100)):]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out[::-1]
