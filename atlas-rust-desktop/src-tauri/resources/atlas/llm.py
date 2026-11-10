"""Small OpenAI-compatible client for Atlas Chat's local llama-swap.

No Atlas Online dependency. Requests go to the local upstream configured in
Atlas Chat's own settings.json. Supports agent JSON-schema actions.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse
from typing import Any

import config
import compute_peers

DEFAULT_MAX_TOKENS = int(config.SETTINGS.get("llm_max_tokens", 2048))
DEFAULT_TEMPERATURE = float(config.SETTINGS.get("llm_temperature", 0.7))

def _base_url() -> str:
    host = config.SETTINGS.get("upstream_host", "127.0.0.1")
    port = int(config.SETTINGS.get("upstream_port", 8080))
    return f"http://{host}:{port}"

def _request(path: str, payload: dict[str, Any] | None = None, timeout: int | None = None):
    base = _base_url()
    peer_host, peer_port, _peer = compute_peers.route((payload or {}).get("model"))
    if peer_host:
        base = f"http://{peer_host}:{peer_port}"
    url = base.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers=compute_peers.headers_for(urlparse(url).hostname, urlparse(url).port, {"Content-Type": "application/json", "Accept": "application/json"}),
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or int(config.SETTINGS.get("llm_timeout", 180))) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        raise RuntimeError(f"Local model endpoint returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"Cannot reach llama-swap at {base}: {exc}. "
            "Check that llama-swap is running and Atlas Chat settings.json has the correct upstream_port."
        ) from exc

def model_ready() -> bool:
    """True only when the configured local model gateway answers /v1/models."""
    try:
        result = _request("/v1/models", timeout=3)
        return isinstance(result, dict) and isinstance(result.get("data"), list)
    except Exception:
        return False

def list_models() -> list[dict[str, Any]]:
    result = _request("/v1/models", timeout=5)
    return result.get("data", []) if isinstance(result, dict) else []

def call_llm(
    prompt: str,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    json_schema: dict[str, Any] | None = None,
    model: str | None = None,
    timeout: int | None = None,
) -> str:
    """Send a prompt and return assistant message content as text.

    This signature is compatible with the agents.py calls:
    call_llm(prompt, temperature=..., max_tokens=..., json_schema=...).
    """
    chosen_model = model or str(config.SETTINGS.get("llm_model", "coder"))
    payload: dict[str, Any] = {
        "model": chosen_model,
        "messages": [{"role": "user", "content": str(prompt)}],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": False,
    }
    if json_schema:
        # llama.cpp / llama-swap OpenAI-compatible structured output format.
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "atlas_agent_action", "strict": True, "schema": json_schema},
        }

    result = _request("/v1/chat/completions", payload, timeout=timeout)
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected chat-completions response: {json.dumps(result)[:2000]}") from exc

    if isinstance(content, str):
        return content
    # Some multimodal-compatible servers return content as an array of parts.
    if isinstance(content, list):
        return "".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    return str(content)
