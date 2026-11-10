"""Defensive, bounded OpenAI-compatible chat tool loop for Atlas MCP."""
from __future__ import annotations

import http.client
import json
import re
import time
import uuid

import compute_peers


_FUNCTION_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")
_SCHEMA_KEYS = {
    "type", "title", "description", "properties", "required", "items",
    "enum", "const", "default", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "minLength", "maxLength", "minItems", "maxItems",
    "uniqueItems", "pattern", "format", "additionalProperties", "oneOf",
    "anyOf", "allOf",
}


class NoLiveTools(RuntimeError):
    """No MCP/library tool is usable right now. The caller should answer with plain chat, not fail."""


def _post(host, port, request, timeout=900):
    """Send a non-streaming completion and preserve upstream diagnostics."""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
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


def _finalize_empty_answer(request, messages, completion, choices, events, host, port):
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
    retry["max_tokens"] = max(1024, min(requested_tokens, 4096))

    recovered = _post_completion(host, port, retry)
    return _ensure_text_only(
        recovered,
        "I couldn't produce a complete final answer. Please retry; no private reasoning is displayed.",
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


def run_tool_loop(request, monitor, record, host, port, max_rounds=5, tool_timeout=60):
    req = dict(request)
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
    req["max_tokens"] = max(1024, min(requested_tokens, 8192))
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
        completion = _post_completion(host, port, {**req, "messages": list(messages)})
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
            return _finalize_empty_answer(req, messages, completion, choices, events, host, port)

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
                try:
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
                        "status": "FAILED", "verification": "not_performed",
                        "server": server_name, "tool": tool_name,
                        "duration_ms": None, "error": error,
                    }

            event["adapter_duration_ms"] = round(
                (time.perf_counter_ns() - adapter_started_ns) / 1_000_000, 3
            )
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
    completion = _post_completion(host, port, {**req, "messages": list(messages)})
    choices = completion.get("choices") if isinstance(completion, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Upstream returned no final completion after the MCP tool-round limit")
    completion = _ensure_text_only(
        completion,
        "Execution stopped at the MCP tool-round limit. Some requested work may be unfinished.",
    )
    return _finalize_empty_answer(req, messages, completion, completion["choices"], events, host, port)


def as_sse(completion):
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
    return "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\ndata: [DONE]\n\n"
