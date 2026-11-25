"""Defensive, bounded OpenAI-compatible chat tool loop for Atlas MCP."""
from __future__ import annotations

import http.client
import json
import os
import threading
import re
import socket
import time
import uuid

import chat_timing
import compute_peers


_FUNCTION_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")
_SCHEMA_KEYS = {
    "type", "title", "description", "properties", "required", "items",
    "enum", "const", "default", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "minLength", "maxLength", "minItems", "maxItems",
    "uniqueItems", "pattern", "format", "additionalProperties", "oneOf",
    "anyOf", "allOf",
}


# ---------- Approval gate: every MCP/bot tool call goes through approval_gate() ----------
# Tiers: "read" runs freely. "write" (local file changes) asks unless ATLAS_WRITE_APPROVAL=auto.
# "consequential" (send, submit, post, delete, pay, shell, network) ALWAYS asks.
# Any tool not listed here is "consequential". Keep this table next to new tool definitions
# (src/mcp_commander.py, book_tools.py).
# ponytail: keyed by tool name only, so a plugin that reuses a built-in name gets its tier.
TOOL_TIERS = {
    # src/mcp_commander.py
    "atlas_project_status": "read", "list_workspace_files": "read", "read_workspace_file": "read",
    "verify_workspace_file": "read", "git_status": "read", "git_diff": "read",
    "atlas_list_files": "read", "atlas_read_file": "read",
    "write_file": "write", "write_project_file": "write",
    "web_search": "consequential",  # the query leaves this PC
    "atlas_list_conversations": "read", "atlas_swarm_runs": "read", "atlas_archive_item": "write",
    # swarm_workspace_mcp.py (atlas-swarm-workspace): read-only discovery of a run's saved files
    "swarm_runs": "read", "swarm_files": "read", "swarm_read_file": "read",
    # book_tools.py (atlas_library)
    "list_books": "read", "read_chapter": "read", "search_book": "read",
    # ctx_sync.py serve (shared project context)
    "ctx_read": "read", "ctx_note": "write",
    # browser_mcp.py (atlas_browser)
    "browser_get_text": "read", "browser_screenshot": "read", "browser_tabs": "read", "browser_wait": "read",
    "browser_open": "write", "browser_click": "write", "browser_type": "write", "browser_press": "write",
    "browser_eval": "write", "browser_close": "write",
    # github_mcp.py (atlas_github): writes post on GitHub, so they always ask
    "github_list_repos": "read", "github_list_issues": "read", "github_get_issue": "read",
    "github_list_prs": "read", "github_get_pr": "read", "github_get_file": "read", "github_list_branches": "read",
    "github_create_issue": "consequential", "github_comment": "consequential", "github_create_branch": "consequential",
    "github_put_file": "consequential", "github_create_pr": "consequential",
    # test_suite_mcp.py (atlas_test_suite)
    "test_suite_list": "read",
    "test_suite_add": "write", "test_suite_update": "write", "test_suite_log_run": "write",
}
APPROVAL_TIMEOUT = 600  # seconds: 10 minutes, then the call is denied
_SECRET_KEY_RE = re.compile(r"pass|secret|token|key|auth|cookie|credential", re.I)
_PENDING = {}
_PENDING_LOCK = threading.Lock()


def tool_tier(tool_name):
    return TOOL_TIERS.get(str(tool_name or ""), "consequential")


def summarize_args(arguments, limit=400):
    """Short, secret-free view of tool arguments for the prompt and the audit log."""
    if not isinstance(arguments, dict):
        return ""
    parts = []
    for key, value in arguments.items():
        if _SECRET_KEY_RE.search(str(key)):
            value = "[hidden]"
        elif not isinstance(value, (int, float, bool)) and value is not None:
            value = str(value)
            value = value if len(value) <= 80 else value[:77] + "..."
        parts.append(f"{key}={value}")
    text = ", ".join(parts)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def pending_approvals():
    with _PENDING_LOCK:
        return [{k: row[k] for k in ("id", "server", "tool", "tier", "args", "created", "expires")}
                for row in _PENDING.values()]


def decide_approval(approval_id, approve):
    """Record the user's click. Returns False when the id is unknown or already decided."""
    with _PENDING_LOCK:
        row = _PENDING.get(str(approval_id))
        if not row or row["decision"]:
            return False
        row["decision"] = "approved" if approve else "denied"
    row["done"].set()
    return True


def approval_gate(server, tool, arguments, record=None, timeout=None):
    """Return (allowed, decision). Blocks while a call waits for Approve / Deny.

    decision is "auto" (read, or write with ATLAS_WRITE_APPROVAL=auto), "approved",
    "denied" or "timeout". Every decision goes to the audit log through record().
    """
    tier = tool_tier(tool)
    args = summarize_args(arguments)
    auto_write = os.environ.get("ATLAS_WRITE_APPROVAL", "ask").strip().lower() == "auto"
    if tier == "read" or (tier == "write" and auto_write):
        decision = "auto"
    else:
        wait = APPROVAL_TIMEOUT if timeout is None else timeout
        now = time.time()
        row = {"id": uuid.uuid4().hex, "server": server, "tool": tool, "tier": tier, "args": args,
               "created": now, "expires": now + wait, "decision": None, "done": threading.Event()}
        with _PENDING_LOCK:
            _PENDING[row["id"]] = row
        row["done"].wait(wait)
        with _PENDING_LOCK:
            _PENDING.pop(row["id"], None)
            decision = row["decision"] or "timeout"
            row["decision"] = decision  # a late click now finds it decided
    if record:
        try:
            record({"status": "APPROVAL", "verification": "not_performed", "server": server, "tool": tool,
                    "tier": tier, "args_summary": args, "decision": decision, "timestamp": time.time()})
        except Exception:
            pass  # the decision stands even when the optional audit sink fails
    return decision in ("auto", "approved"), decision


def denied_message(tool, decision):
    why = "timed out after 10 minutes with no answer" if decision == "timeout" else "was denied by the user"
    return f"The tool call '{tool}' {why}. It did not run. Do not retry it; tell the user what you wanted to do."


class Cancelled(RuntimeError):
    """The chat window went away. Stop the model call so the single llama.cpp slot is free again."""


class CancelToken:
    """Set by the server when the client disconnects. set() also cuts the open upstream socket,
    which makes llama-server stop generating (an orphaned generation blocks the next message)."""

    def __init__(self):
        self._event = threading.Event()
        self._conn = None

    def attach(self, conn):
        self._conn = conn
        if self._event.is_set():
            self._cut()

    def _cut(self):
        try:
            sock = getattr(self._conn, "sock", None)
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass

    def set(self):
        self._event.set()
        self._cut()

    def is_set(self):
        return self._event.is_set()

    def check(self):
        if self._event.is_set():
            raise Cancelled("client disconnected")


_ACTIVE = threading.local()  # per tool-loop thread: cancel token and request id


def _token():
    return getattr(_ACTIVE, "cancel", None)


class NoLiveTools(RuntimeError):
    """No MCP/library tool is usable right now. The caller should answer with plain chat, not fail."""


def _is_loaded(host, port, model):
    """True when llama-swap already holds this model in memory (None when it does not say)."""
    try:
        import context_engine
        names = context_engine.running_models(host, port, compute_peers.headers_for(host, port, {}))
        return None if names is None else str(model) in names
    except Exception:
        return None


def _post(host, port, request, timeout=900):
    """Send a non-streaming completion and preserve upstream diagnostics."""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    tok = _token()
    if tok is not None:
        tok.attach(conn)
    try:
        body = json.dumps(request, ensure_ascii=False).encode("utf-8")
        conn.request(
            "POST", "/v1/chat/completions", body=body,
            headers=compute_peers.headers_for(host, port, {"Content-Type": "application/json", "Accept": "application/json"}),
        )
        response = conn.getresponse()
        raw = response.read()
        decoded = raw.decode("utf-8", "replace")
        if not 200 <= response.status < 300:
            raise RuntimeError(f"llama-swap upstream HTTP {response.status}: {decoded[:4000]}")
        try:
            result = json.loads(decoded)
        except (ValueError, TypeError) as exc:
            raise RuntimeError(f"Upstream returned invalid JSON: {decoded[:1000]}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("Upstream returned a non-object completion")
        return result
    finally:
        conn.close()


def _post_completion(host, port, request):
    """Stable, patchable transport used by the bounded tool loop."""
    return _post(host, port, request)


def _safe_schema(schema, depth=0):
    """Keep a bounded, provider-compatible subset of an MCP input schema."""
    if depth > 12 or not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    out = {}
    for key, value in schema.items():
        if key not in _SCHEMA_KEYS:
            continue
        if key == "properties":
            if isinstance(value, dict):
                out[key] = {
                    name: _safe_schema(child, depth + 1)
                    for name, child in list(value.items())[:128]
                    if isinstance(name, str) and isinstance(child, dict)
                }
        elif key in ("items", "additionalProperties") and isinstance(value, dict):
            out[key] = _safe_schema(value, depth + 1)
        elif key in ("oneOf", "anyOf", "allOf") and isinstance(value, list):
            out[key] = [_safe_schema(child, depth + 1) for child in value[:16] if isinstance(child, dict)]
        elif key == "required" and isinstance(value, list):
            out[key] = [name for name in value[:128] if isinstance(name, str)]
        elif key == "enum" and isinstance(value, list):
            out[key] = [item for item in value[:128] if item is None or isinstance(item, (str, int, float, bool))]
        elif key in ("default", "const"):
            if value is None or isinstance(value, (str, int, float, bool)):
                out[key] = value
        elif isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value[:2000] if isinstance(value, str) else value

    # MCP tool input schemas are object schemas. Preserve their properties and
    # constraints but normalize absent/unsupported top-level types to object.
    if out.get("type") != "object":
        out["type"] = "object"
    return out


def _tool_definitions(monitor, reserved_names=None):
    """Build provider-safe names and a lossless map back to MCP server/tool IDs."""
    available, lookup = [], {}
    used = set(reserved_names or ())
    status = monitor.status() or {}
    servers = status.get("servers", []) if isinstance(status, dict) else []

    for server in servers if isinstance(servers, list) else []:
        if not isinstance(server, dict) or server.get("state") != "online":
            continue
        server_name = str(server.get("name") or "").strip()
        tools = server.get("tools", [])
        if not server_name or not isinstance(tools, list):
            continue

        for tool in tools:
            if not isinstance(tool, dict):
                continue
            original_name = str(tool.get("name") or "").strip()
            if not original_name:
                continue

            public_name = f"{server_name}__{original_name}"
            safe_name = _FUNCTION_NAME_RE.sub("_", public_name)[:64]
            if not safe_name or safe_name in used:
                # Deterministic fallback keeps the name stable across requests.
                suffix = uuid.uuid5(uuid.NAMESPACE_URL, public_name).hex
                safe_name = ("mcp_" + suffix)[:64]
                counter = 1
                while safe_name in used:
                    tail = f"_{counter}"
                    safe_name = ("mcp_" + suffix[:64 - 4 - len(tail)] + tail)[:64]
                    counter += 1

            used.add(safe_name)
            raw_schema = tool.get("inputSchema")
            schema = _safe_schema(raw_schema if isinstance(raw_schema, dict) else {})
            available.append({
                "type": "function",
                "function": {
                    "name": safe_name,
                    "description": str(tool.get("description") or "")[:1000],
                    "parameters": schema,
                },
            })
            lookup[safe_name] = (server_name, original_name)

    return available, lookup


def _content_text(message):
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part).strip()
    return ""


def _strip_private_reasoning(completion):
    if not isinstance(completion, dict):
        return completion
    choices = completion.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if isinstance(choice, dict) and isinstance(choice.get("message"), dict):
                choice["message"].pop("reasoning_content", None)
    return completion


def _ensure_text_only(completion, fallback):
    """Never return a final response that still contains unexecuted tool calls."""
    choices = completion.get("choices") if isinstance(completion, dict) else None
    if not isinstance(choices, list) or not choices:
        completion = dict(completion) if isinstance(completion, dict) else {}
        choices = [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": fallback}}]
        completion["choices"] = choices
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message")
    if not isinstance(message, dict):
        message = {"role": "assistant", "content": fallback}
    else:
        message = dict(message)
    message.pop("tool_calls", None)
    message.pop("function_call", None)
    message.pop("reasoning_content", None)
    if not _content_text(message):
        message["content"] = fallback
    choice["message"] = message
    choice["finish_reason"] = "stop"
    choices[0] = choice
    completion["choices"] = choices
    return completion


def normalize_system_messages(messages):
    """Return a copy of messages with ALL system content merged into ONE leading system message.

    Strict chat templates (Qwen and others, served through llama-swap) raise
    "System message must be at the beginning" if a system message is not first or
    if there is more than one. Every place that injects system text calls this last.
    """
    system_parts, rest = [], []
    for item in messages:
        if isinstance(item, dict) and item.get("role") == "system":
            system_parts.append(item.get("content"))
        else:
            rest.append(item)
    if not system_parts:
        return list(messages)
    if all(isinstance(part, str) or part is None for part in system_parts):
        merged = "\n\n".join(part for part in system_parts if part)
    else:
        merged = []
        for part in system_parts:
            if isinstance(part, list):
                merged.extend(part)
            elif part:
                merged.append({"type": "text", "text": str(part)})
    return [{"role": "system", "content": merged}] + rest


def _finalize_empty_answer(request, messages, completion, choices, events, host, port, on_delta=None):
    """Make one bounded text-only retry if the model returned no user-facing text."""
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = choice.get("message")
    if not isinstance(message, dict):
        message = {}
    if _content_text(message):
        return _strip_private_reasoning(completion), events
    if message.get("tool_calls"):
        return _ensure_text_only(completion, "Execution stopped before a user-facing answer was produced."), events

    clean_messages = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        if item.get("role") == "assistant" and not item.get("tool_calls") and not _content_text(item):
            continue
        clean_messages.append({key: value for key, value in item.items() if key != "reasoning_content"})

    # Sent as a user turn, not "system": strict chat templates (Qwen etc.) raise
    # "System message must be at the beginning" for a system message after turn 0.
    clean_messages.append({
        "role": "user",
        "content": (
            "Produce the user-facing final answer now. Do not call tools. "
            "Do not reveal private reasoning. Summarize only the conversation and tool results."
        ),
    })
    retry = dict(request)
    retry.pop("tools", None)
    retry.pop("tool_choice", None)
    retry["stream"] = False
    retry["messages"] = clean_messages
    try:
        requested_tokens = int(retry.get("max_tokens") or 2048)
    except (TypeError, ValueError, OverflowError):
        requested_tokens = 2048
    retry["chat_template_kwargs"] = {**(retry.get("chat_template_kwargs") or {}), "enable_thinking": False}
    retry["max_tokens"] = max(1024, min(requested_tokens, 4096))  # thinking is off for this retry

    recovered = _complete_streaming(host, port, retry, on_delta) if on_delta is not None else _complete(host, port, retry)
    return _ensure_text_only(
        recovered,
        "The model used its whole token budget on hidden reasoning and gave no answer, even after a retry with thinking off. Send the message again, or ask a shorter question.",
    ), events


def _tool_call_id(call, used_ids):
    candidate = str(call.get("id") or "").strip()
    if not candidate or candidate in used_ids:
        candidate = "call_atlas_" + uuid.uuid4().hex
        while candidate in used_ids:
            candidate = "call_atlas_" + uuid.uuid4().hex
        call["id"] = candidate
    used_ids.add(candidate)
    return candidate


_USAGE = threading.local()


def _complete(host, port, request):
    """_post_completion plus a running total of usage over all tool rounds of this request."""
    completion = _post_completion(host, port, request)
    usage = completion.get("usage") if isinstance(completion, dict) else None
    total = getattr(_USAGE, "total", None)
    if isinstance(usage, dict) and total is not None:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if isinstance(usage.get(key), (int, float)):
                total[key] = total.get(key, 0) + int(usage[key])
        total["rounds"] = total.get("rounds", 0) + 1
    return completion


def first_token_timeout():
    """Seconds to wait for the model server to start answering. A cold model load takes about 2 minutes."""
    try:
        return max(30.0, float(os.environ.get("ATLAS_FIRST_TOKEN_TIMEOUT", "300")))
    except ValueError:
        return 300.0


def thinking_enabled(request):
    kw = request.get("chat_template_kwargs")
    return not (isinstance(kw, dict) and kw.get("enable_thinking") is False)


def token_budget(request, requested, cap):
    """max_tokens for a request. A thinking model spends tokens on hidden reasoning before the answer,
    so a small budget (the UI sends 2048) ends with reasoning only and no answer. Give thinking a larger floor."""
    floor = 8192 if thinking_enabled(request) else 1024
    return max(floor, min(requested, cap))


def _stream_completion(host, port, request, on_delta=None):
    """Stream an OpenAI-compatible completion from upstream.

    Forwards each content delta to on_delta(text) as it arrives so the UI can show
    tokens live instead of waiting for the whole generation. Returns a completion dict
    shaped exactly like _post() (choices[0].message with content and/or tool_calls, plus
    usage/timings when the server sends them). Falls back to the proven non-streaming
    _post() when the stream cannot start, or fails before a single token was emitted.
    """
    req = dict(request)
    req["stream"] = True
    opts = req.get("stream_options") if isinstance(req.get("stream_options"), dict) else {}
    req["stream_options"] = {**opts, "include_usage": True}
    tok = _token()
    try:
        conn = http.client.HTTPConnection(host, port, timeout=first_token_timeout())
        if tok is not None:
            tok.attach(conn)
        body = json.dumps(req, ensure_ascii=False).encode("utf-8")
        conn.request(
            "POST", "/v1/chat/completions", body=body,
            headers=compute_peers.headers_for(host, port, {"Content-Type": "application/json", "Accept": "text/event-stream"}),
        )
        response = conn.getresponse()
        if getattr(conn, "sock", None) is not None:
            conn.sock.settimeout(900)  # the first-token limit is over; later gaps may be long
    except TimeoutError as exc:
        conn.close()
        if tok is not None:
            tok.check()
        raise RuntimeError(
            f"No first token from the model after {first_token_timeout():.0f} s. The model server may be stuck "
            "(model load, or an earlier request holding the only slot). Nothing was lost: send the message again. "
            "See logs\\llama-swap.log in the Atlas data folder.") from exc
    except (OSError, http.client.HTTPException):
        if tok is not None:
            tok.check()
        # Could not even open the stream: use the proven non-streaming transport.
        return _post(host, port, {**request, "stream": False})

    emitted = False
    try:
        if not 200 <= response.status < 300:
            raw = response.read().decode("utf-8", "replace")
            raise RuntimeError(f"llama-swap upstream HTTP {response.status}: {raw[:4000]}")

        ctype = (response.getheader("Content-Type") or "").lower()
        if "text/event-stream" not in ctype:
            # Upstream ignored stream=true (some peers / proxies answer with one JSON body):
            # parse it as a normal completion and surface the whole answer as a single delta.
            raw = response.read().decode("utf-8", "replace")
            try:
                completion = json.loads(raw)
            except (ValueError, TypeError) as exc:
                raise RuntimeError(f"Upstream returned invalid JSON: {raw[:1000]}") from exc
            if not isinstance(completion, dict):
                raise RuntimeError("Upstream returned a non-object completion")
            if callable(on_delta):
                choices = completion.get("choices")
                choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
                text = _content_text(choice.get("message")) if isinstance(choice.get("message"), dict) else ""
                if text:
                    try:
                        on_delta(text)
                    except Exception:
                        pass
            return completion

        content_parts = []
        reasoning_chars = 0
        tool_calls = {}
        finish_reason = None
        usage = None
        timings = None
        meta = {"id": None, "model": None, "created": None}
        buf = ""
        while True:
            chunk = response.read1(8192) if hasattr(response, "read1") else response.read(8192)
            if tok is not None:
                tok.check()
            if not chunk:
                break
            buf += chunk.decode("utf-8", "replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    continue
                try:
                    j = json.loads(data)
                except (ValueError, TypeError):
                    continue
                if not isinstance(j, dict):
                    continue
                if j.get("error"):  # llama-swap / llama-server reports a failure inside the stream
                    err = j["error"]
                    text = err.get("message") if isinstance(err, dict) else err
                    raise RuntimeError(f"llama-swap upstream error: {str(text)[:500]}")
                for key in ("id", "model", "created"):
                    if j.get(key) and not meta[key]:
                        meta[key] = j.get(key)
                if isinstance(j.get("usage"), dict):
                    usage = j["usage"]
                if isinstance(j.get("timings"), dict):
                    timings = j["timings"]
                choices = j.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                ch0 = choices[0] if isinstance(choices[0], dict) else {}
                if ch0.get("finish_reason"):
                    finish_reason = ch0["finish_reason"]
                delta = ch0.get("delta") if isinstance(ch0.get("delta"), dict) else {}
                if isinstance(delta.get("reasoning_content"), str):
                    reasoning_chars += len(delta["reasoning_content"])
                piece = delta.get("content")
                if isinstance(piece, str) and piece:
                    content_parts.append(piece)
                    if callable(on_delta):
                        on_delta(piece)
                        emitted = True
                dtc = delta.get("tool_calls")
                if isinstance(dtc, list):
                    for tc in dtc:
                        if not isinstance(tc, dict):
                            continue
                        slot = tool_calls.setdefault(
                            tc.get("index", 0),
                            {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        if tc.get("type"):
                            slot["type"] = tc["type"]
                        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                        if fn.get("name"):
                            slot["function"]["name"] = fn["name"]
                        if isinstance(fn.get("arguments"), str):
                            slot["function"]["arguments"] += fn["arguments"]
    except RuntimeError:
        raise  # a real upstream error (non-2xx); surface it like _post() does
    except Exception:
        if tok is not None and tok.is_set():
            raise Cancelled("client disconnected")
        if emitted:
            raise  # mid-stream failure after tokens were shown: do not silently restart
        return _post(host, port, {**request, "stream": False})
    finally:
        conn.close()

    if not content_parts and not tool_calls and not reasoning_chars and not usage and not timings and not finish_reason:
        # The stream ended with nothing: no text, no tool call, no usage. Typical when llama-server exits
        # or llama-swap drops the request while the model loads. Never show this as a finished empty reply.
        raise RuntimeError("The model server closed the stream with no answer (the model may have failed to load "
                           "or crashed). See logs\\llama-swap.log in the Atlas data folder, then try again.")
    message = {"role": "assistant", "content": "".join(content_parts)}
    if tool_calls:
        message["tool_calls"] = [tool_calls[k] for k in sorted(tool_calls.keys())]
        message["content"] = "".join(content_parts) or None
    completion = {
        "id": meta["id"] or "chatcmpl-atlas",
        "object": "chat.completion",
        "created": meta["created"] or int(time.time()),
        "model": meta["model"] or req.get("model") or "atlas",
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason or ("tool_calls" if tool_calls else "stop"),
        }],
    }
    if isinstance(usage, dict):
        completion["usage"] = usage
    if isinstance(timings, dict):
        completion["timings"] = timings
    if reasoning_chars:
        completion["atlas_reasoning_chars"] = reasoning_chars  # diagnostics only: thinking text that never reaches the chat
    return completion


_RECOVER_LAST = [0.0]
_REAP_PS = ("$ids=(Get-Process).Id; Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" | "
            "Where-Object { $ids -notcontains $_.ParentProcessId } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }")


def reap_orphan_llama_servers():
    """Windows only: stop llama-server.exe processes whose parent (llama-swap) is gone. They hold the port and
    the VRAM, and the next model start then fails. Returns the list of stopped process ids."""
    if os.name != "nt" or os.environ.get("ATLAS_NO_REAP") == "1":
        return []
    import subprocess
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _REAP_PS],
                             capture_output=True, text=True, timeout=20,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:
        return []
    return [int(x) for x in out.split() if x.isdigit()]


def recover_model_server(host, port, reason=""):
    """After a failed model start: unload through llama-swap and stop orphan llama-server processes.
    At most once per 15 s. Returns True when a retry is worth trying."""
    low = str(reason).lower()
    if not any(k in low for k in ("closed the stream", "exited prematurely", "502", "bad gateway", "upstream")):
        return False
    if host not in ("127.0.0.1", "localhost", "::1") or time.time() - _RECOVER_LAST[0] < 15:
        return False
    _RECOVER_LAST[0] = time.time()
    try:
        c = http.client.HTTPConnection(host, port, timeout=10)
        c.request("POST", "/unload")
        c.getresponse().read()
        c.close()
    except Exception:
        pass
    reap_orphan_llama_servers()
    time.sleep(2)
    return True


def _complete_streaming(host, port, request, on_delta):
    """Streaming sibling of _complete(): forwards content deltas and keeps the usage total."""
    try:
        completion = _stream_completion(host, port, request, on_delta=on_delta)
    except RuntimeError as first:
        # The model failed to start (llama-swap: "upstream command exited prematurely", or an empty stream)
        # before any token was shown. Clear dead model processes once and try again, so the user does not
        # have to stop llama-server by hand.
        tok = getattr(_ACTIVE, "cancel", None)
        if (tok is not None and tok.is_set()) or not recover_model_server(host, port, str(first)):
            raise
        completion = _stream_completion(host, port, request, on_delta=on_delta)
    usage = completion.get("usage") if isinstance(completion, dict) else None
    total = getattr(_USAGE, "total", None)
    if isinstance(usage, dict) and total is not None:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if isinstance(usage.get(key), (int, float)):
                total[key] = total.get(key, 0) + int(usage[key])
        total["rounds"] = total.get("rounds", 0) + 1
    return completion


def summarize_tool_events(events):
    """Return a UI-safe compact list of executed tool calls for the chat Action History card."""
    out = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        dur = ev.get("duration_ms")
        if dur is None:
            dur = ev.get("adapter_duration_ms")
        out.append({
            "tool": str(ev.get("tool") or "tool")[:120],
            "server": str(ev.get("server") or "")[:80],
            "status": str(ev.get("status") or "UNKNOWN")[:40],
            "duration_ms": round(float(dur), 1) if isinstance(dur, (int, float)) else None,
            "args_preview": str(ev.get("args_preview") or "")[:240],
            "error": str(ev.get("error") or "")[:300] or None,
            "trace_id": str(ev.get("trace_id") or ev.get("call_id") or "")[:64] or None,
        })
    return out


def has_live_tools(monitor, request=None):
    """Return True when at least one live MCP tool is available for this request."""
    existing = (request or {}).get("tools") or []
    if not isinstance(existing, list):
        existing = []
    reserved_names = {
        item.get("function", {}).get("name")
        for item in existing
        if isinstance(item, dict) and isinstance(item.get("function"), dict)
        and isinstance(item.get("function", {}).get("name"), str)
    }
    available, _ = _tool_definitions(monitor, reserved_names)
    return bool(available)


def run_tool_loop(request, monitor, record, host, port, max_rounds=5, tool_timeout=60, on_event=None, on_delta=None,
                  cancel=None, trace_id=None):
    """Bounded tool loop. The final completion carries atlas_usage_total and atlas_tool_events.

    When on_delta is given, the model's answer is produced with a streaming upstream call
    and each content token is forwarded to on_delta(text) as it arrives.
    """
    _USAGE.total = {}
    _ACTIVE.cancel, _ACTIVE.trace_id = cancel, trace_id
    try:
        completion, events = _run_tool_loop(
            request, monitor, record, host, port, max_rounds, tool_timeout, on_event=on_event, on_delta=on_delta
        )
    finally:
        total, _USAGE.total = _USAGE.total, None
        _ACTIVE.cancel = _ACTIVE.trace_id = None
    if isinstance(completion, dict) and total:
        completion["atlas_usage_total"] = total
    if isinstance(completion, dict) and events:
        completion["atlas_tool_events"] = summarize_tool_events(events)
    return completion, events


def _run_tool_loop(request, monitor, record, host, port, max_rounds=5, tool_timeout=60, on_event=None, on_delta=None):
    def _do_complete(payload):
        # Stream the model call when the caller wants live tokens; the non-streaming
        # path (on_delta=None) stays byte-for-byte identical and keeps using _post_completion.
        tok = _token()
        if tok is not None:
            tok.check()
        t0, first, loaded = time.time(), [None], _is_loaded(host, port, payload.get("model"))

        def timed_delta(piece):
            if first[0] is None:
                first[0] = time.time()
            return on_delta(piece)

        completion, err = None, None
        try:
            if on_delta is not None:
                completion = _complete_streaming(host, port, payload, timed_delta)
            else:
                completion = _complete(host, port, payload)
            return completion
        except Exception as exc:
            err = f"error:{type(exc).__name__}:{str(exc)[:120]}"
            raise
        finally:
            t1 = time.time()
            chat_timing.write(chat_timing.entry(
                getattr(_ACTIVE, "trace_id", None), payload.get("model"), t0,
                first[0] or (t1 if on_delta is None else None), t1, completion, loaded,
                "cancelled" if (tok is not None and tok.is_set()) else err, chat_timing.breakdown(payload)))

    req = dict(request)
    req.pop("stream_options", None)
    messages = list(req.get("messages") or [])
    events = []
    if not messages or any(not isinstance(item, dict) for item in messages):
        raise ValueError("Chat completion requires a non-empty messages array of objects")
    messages = normalize_system_messages(messages)
    req["messages"] = messages

    existing = req.get("tools") or []
    if not isinstance(existing, list):
        existing = []
    reserved_names = {
        item.get("function", {}).get("name")
        for item in existing
        if isinstance(item, dict) and isinstance(item.get("function"), dict)
        and isinstance(item.get("function", {}).get("name"), str)
    }
    available, lookup = _tool_definitions(monitor, reserved_names)
    if not available:
        raise NoLiveTools("No live MCP tools are available")

    req["stream"] = False
    try:
        requested_tokens = int(req.get("max_tokens") or 2048)
    except (TypeError, ValueError, OverflowError):
        requested_tokens = 2048
    req["max_tokens"] = token_budget(req, requested_tokens, 16384)
    req["messages"] = messages
    req["tools"] = existing + available
    req["tool_choice"] = "auto"

    try:
        round_limit = max(1, min(8, int(max_rounds)))
    except (TypeError, ValueError, OverflowError):
        round_limit = 5
    try:
        timeout = max(1, min(120, int(tool_timeout)))
    except (TypeError, ValueError, OverflowError):
        timeout = 60

    attempted_operations = set()
    for _round_no in range(round_limit):
        completion = _do_complete({**req, "messages": list(messages)})
        choices = completion.get("choices") if isinstance(completion, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Upstream returned no completion choices")
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Upstream returned an invalid assistant message")
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list):
            raise RuntimeError("Upstream returned an invalid tool_calls array")
        if not calls:
            messages.append(message)
            return _finalize_empty_answer(req, messages, completion, choices, events, host, port, on_delta=on_delta)

        # Preserve the assistant tool-call message before its matching tool
        # responses, as required by the OpenAI-compatible conversation format.
        messages.append(message)
        used_call_ids = set()
        for call_index, raw_call in enumerate(calls):
            call = raw_call if isinstance(raw_call, dict) else {}
            if not isinstance(raw_call, dict):
                calls[call_index] = call
            if not isinstance(call.get("function"), dict):
                call["function"] = {}
            call.setdefault("type", "function")
            fn = call["function"]
            public_name = str(fn.get("name") or "")
            target = lookup.get(public_name)
            call_id = _tool_call_id(call, used_call_ids)

            raw_arguments = fn.get("arguments", "{}")
            if raw_arguments is None:  # tools without parameters are often called with "arguments": null
                raw_arguments = "{}"
            args_error = None
            if isinstance(raw_arguments, dict):
                arguments = raw_arguments
            elif isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments or "{}")
                except (ValueError, TypeError) as exc:
                    arguments = None
                    args_error = f"Invalid JSON tool arguments: {exc}"
            else:
                arguments = None
                args_error = "Tool arguments must be a JSON object or JSON object string"

            if args_error is None and not isinstance(arguments, dict):
                args_error = "Tool arguments must decode to a JSON object"

            operation_key = None
            if args_error is None:
                operation_key = json.dumps(
                    {"tool": public_name, "arguments": arguments},
                    sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                )

            adapter_started_ns = time.perf_counter_ns()
            if args_error:
                event = {
                    "status": "FAILED", "verification": "not_performed",
                    "tool": public_name, "error": args_error, "duration_ms": None,
                }
                content = json.dumps({"error": args_error}, ensure_ascii=False)
            elif not target:
                error = "Unknown or invalid MCP tool name"
                event = {
                    "status": "FAILED", "verification": "not_performed",
                    "tool": public_name, "error": error, "duration_ms": None,
                }
                content = json.dumps({"error": error}, ensure_ascii=False)
            elif operation_key in attempted_operations:
                error = "Duplicate MCP operation suppressed; it was already attempted."
                event = {
                    "status": "FAILED", "verification": "not_performed",
                    "server": target[0], "tool": target[1],
                    "duration_ms": None, "error": error, "duplicate_suppressed": True,
                }
                content = json.dumps({"error": error, "duplicate_suppressed": True}, ensure_ascii=False)
            else:
                # Reserve before execution: a timeout/uncertain result must not
                # cause a repeated model call to execute the same operation.
                attempted_operations.add(operation_key)
                server_name, tool_name = target
                allowed, decision = approval_gate(server_name, tool_name, arguments, record)
                try:
                    if not allowed:
                        raise PermissionError(denied_message(tool_name, decision))
                    evidence = monitor.call_tool(server_name, tool_name, arguments, timeout=timeout)
                    if not isinstance(evidence, dict):
                        raise RuntimeError("MCP monitor returned a non-object execution result")
                    content = json.dumps(evidence.get("result", {}), ensure_ascii=False, default=str)
                    # Preserve the monitor's execution evidence exactly; adapter
                    # timing is a separate measurement around this whole step.
                    event = {
                        **evidence,
                        "status": evidence.get("status", "UNKNOWN"),
                        "server": server_name,
                        "tool": tool_name,
                    }
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    content = json.dumps({"error": error}, ensure_ascii=False)
                    event = {
                        "status": "FAILED" if allowed else "DENIED", "verification": "not_performed",
                        "server": server_name, "tool": tool_name,
                        "duration_ms": None, "error": error, "approval": decision,
                    }

            event["adapter_duration_ms"] = round(
                (time.perf_counter_ns() - adapter_started_ns) / 1_000_000, 3
            )
            if args_error is None:
                event.setdefault("args_preview", summarize_args(arguments))
            event.setdefault("call_id", call_id)
            event.setdefault("timestamp", time.time())
            events.append(event)
            try:
                recorded = record(event)
                if isinstance(recorded, dict):
                    event = recorded
                    events[-1] = recorded
            except Exception as exc:
                # Do not lose the tool result because an optional audit sink failed.
                event["audit_record_error"] = f"{type(exc).__name__}: {exc}"

            if callable(on_event):
                try:
                    on_event(summarize_tool_events(events))
                except Exception:
                    pass

            messages.append({"role": "tool", "tool_call_id": call_id, "content": content[:32000]})

        req["messages"] = messages

    # Hard stop: after the round budget, no further tool definitions are sent.
    req.pop("tools", None)
    req.pop("tool_choice", None)
    # User turn, not "system": see note in _finalize_empty_answer.
    messages.append({
        "role": "user",
        "content": (
            "The MCP tool-round limit was reached. Do not call tools. "
            "Summarize completed work and clearly state anything unfinished."
        ),
    })
    completion = _complete(host, port, {**req, "messages": list(messages)})
    choices = completion.get("choices") if isinstance(completion, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Upstream returned no final completion after the MCP tool-round limit")
    completion = _ensure_text_only(
        completion,
        "Execution stopped at the MCP tool-round limit. Some requested work may be unfinished.",
    )
    return _finalize_empty_answer(req, messages, completion, completion["choices"], events, host, port, on_delta=on_delta)


def as_sse(completion, events=None):
    """Encode a completed OpenAI response as the SSE format Atlas's UI expects."""
    choices = completion.get("choices") if isinstance(completion, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = _content_text(message) or "The model did not return a user-facing answer. Please retry."
    chunk = {
        "id": completion.get("id", "chatcmpl-atlas") if isinstance(completion, dict) else "chatcmpl-atlas",
        "object": "chat.completion.chunk",
        "created": completion.get("created", int(time.time())) if isinstance(completion, dict) else int(time.time()),
        "model": completion.get("model", "atlas") if isinstance(completion, dict) else "atlas",
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "content": content},
            "finish_reason": choice.get("finish_reason") or "stop",
        }],
    }
    if isinstance(completion, dict):
        # Real token numbers for the UI: usage of the final round (= context size) and the sum of all rounds.
        if isinstance(completion.get("usage"), dict):
            chunk["usage"] = completion["usage"]
        if isinstance(completion.get("timings"), dict):
            chunk["timings"] = completion["timings"]
        if isinstance(completion.get("atlas_usage_total"), dict):
            chunk["atlas_usage_total"] = completion["atlas_usage_total"]
        tool_events = completion.get("atlas_tool_events")
        if not tool_events and events:
            tool_events = summarize_tool_events(events)
        if isinstance(tool_events, list) and tool_events:
            chunk["atlas_tool_events"] = tool_events
    return "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\ndata: [DONE]\n\n"


def as_sse_trailer(completion, events=None):
    """Closing SSE chunk when the answer was already streamed live: it carries only the
    final usage/timings/tool events (no content, so nothing is duplicated) and ends the
    stream with [DONE]."""
    chunk = {
        "id": completion.get("id", "chatcmpl-atlas") if isinstance(completion, dict) else "chatcmpl-atlas",
        "object": "chat.completion.chunk",
        "created": completion.get("created", int(time.time())) if isinstance(completion, dict) else int(time.time()),
        "model": completion.get("model", "atlas") if isinstance(completion, dict) else "atlas",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    if isinstance(completion, dict):
        if isinstance(completion.get("usage"), dict):
            chunk["usage"] = completion["usage"]
        if isinstance(completion.get("timings"), dict):
            chunk["timings"] = completion["timings"]
        if isinstance(completion.get("atlas_usage_total"), dict):
            chunk["atlas_usage_total"] = completion["atlas_usage_total"]
        tool_events = completion.get("atlas_tool_events")
        if not tool_events and events:
            tool_events = summarize_tool_events(events)
        if isinstance(tool_events, list) and tool_events:
            chunk["atlas_tool_events"] = tool_events
    return "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\ndata: [DONE]\n\n"
