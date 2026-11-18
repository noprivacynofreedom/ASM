"""Optional cloud models for /swarm: Gemini (planning) and DeepSeek via OpenRouter (review).

No extra packages: plain urllib, so it works in the bundled Python.
Keys come ONLY from environment variables, never from files:
  GEMINI_API_KEY, OPENROUTER_API_KEY.  Set ATLAS_CLOUD_SWARM=0 to turn cloud off.
Gemini: ATLAS_GEMINI_MODEL takes one model name or a comma list, tried in order. A busy answer
(HTTP 429/5xx) is retried a few times; a missing model (404) moves on to the next model.
ATLAS_CLOUD_PROXY=http://host:port sends only the cloud calls through a proxy.
"""
from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.request

# Google retires Gemini models without much warning (gemini-2.5-flash answers 404 for new users), so keep a list.
GEMINI_MODEL = os.environ.get("ATLAS_GEMINI_MODEL", "gemini-3.8-flash,gemini-3.7-flash,gemini-flash-latest")
RETRY_CODES = (429, 500, 502, 503, 504)  # busy or broken for a moment: try the same model again
RETRY_WAITS = (2, 5)  # seconds to wait before the 2nd and the 3rd try
GEMINI_ATTEMPT_SECONDS = 45  # one try gets this long. A stalled connection is dropped and tried again.
GEMINI_BUDGET_SECONDS = 100  # all tries together; after this the swarm uses the local model
DEEPSEEK_MODEL = os.environ.get("ATLAS_DEEPSEEK_MODEL", "deepseek/deepseek-chat")
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
_MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
_GITHUB_URL = "https://models.inference.ai.azure.com/chat/completions"
_GROK_URL = "https://api.x.ai/v1/chat/completions"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
PROVIDERS = {
    "gemini": ("Gemini", "GEMINI_API_KEY"),
    "deepseek": ("DeepSeek", "OPENROUTER_API_KEY"),
    "groq": ("Groq", "GROQ_API_KEY"),
    "cerebras": ("Cerebras", "CEREBRAS_API_KEY"),
    "openrouter": ("OpenRouter Free", "OPENROUTER_API_KEY"),
    "mistral": ("Mistral", "MISTRAL_API_KEY"),
    "github": ("GitHub Models", "GITHUB_TOKEN"),
    "abliterated": ("Abliterated Cloud", "OPENROUTER_API_KEY"),
}

# Cloud model picker entries. Keys come only from environment variables, never from files.
CLOUD_MODELS = (
    {"id": "cloud:gemini", "provider": "gemini", "label": "☁ Gemini Flash (Google Free Tier)",
     "env": ("GEMINI_API_KEY",), "model_env": "ATLAS_GEMINI_MODEL", "default_model": "gemini-3.8-flash",
     "url_env": "ATLAS_GEMINI_URL", "default_url": _GEMINI_URL, "free": True, "context_window": 131072},
    {"id": "cloud:openrouter-free", "provider": "openrouter", "label": "☁ OpenRouter Auto (Free Router)",
     "env": ("OPENROUTER_API_KEY",), "model_env": "ATLAS_OPENROUTER_FREE_MODEL", "default_model": "openrouter/free",
     "url_env": "ATLAS_OPENROUTER_URL", "default_url": _OPENROUTER_URL, "free": True, "context_window": 65536},
    {"id": "cloud:qwen-coder-free", "provider": "openrouter", "label": "☁ Qwen3 Coder (OpenRouter Free)",
     "env": ("OPENROUTER_API_KEY",), "model_env": "ATLAS_QWEN_FREE_MODEL", "default_model": "qwen/qwen3-coder:free",
     "url_env": "ATLAS_OPENROUTER_URL", "default_url": _OPENROUTER_URL, "free": True, "context_window": 65536},
    {"id": "cloud:groq", "provider": "groq", "label": "☁ Groq Llama 3.3 70B (Free Tier)",
     "env": ("GROQ_API_KEY",), "model_env": "ATLAS_GROQ_MODEL", "default_model": "llama-3.3-70b-versatile",
     "url_env": "ATLAS_GROQ_URL", "default_url": _GROQ_URL, "free": True, "context_window": 131072},
    {"id": "cloud:cerebras", "provider": "cerebras", "label": "☁ Cerebras Llama 3.3 70B (Free Tier)",
     "env": ("CEREBRAS_API_KEY",), "model_env": "ATLAS_CEREBRAS_MODEL", "default_model": "llama-3.3-70b",
     "url_env": "ATLAS_CEREBRAS_URL", "default_url": _CEREBRAS_URL, "free": True, "context_window": 65536},
    {"id": "cloud:mistral", "provider": "mistral", "label": "☁ Mistral Small (Free Tier)",
     "env": ("MISTRAL_API_KEY",), "model_env": "ATLAS_MISTRAL_MODEL", "default_model": "mistral-small-latest",
     "url_env": "ATLAS_MISTRAL_URL", "default_url": _MISTRAL_URL, "free": True, "context_window": 32768},
    {"id": "cloud:github", "provider": "github", "label": "☁ GitHub Models GPT-4o Mini (Free Tier)",
     "env": ("GITHUB_TOKEN", "GH_MODELS_KEY"), "model_env": "ATLAS_GITHUB_MODEL", "default_model": "gpt-4o-mini",
     "url_env": "ATLAS_GITHUB_URL", "default_url": _GITHUB_URL, "free": True, "context_window": 65536},
    {"id": "cloud:deepseek", "provider": "deepseek", "label": "☁ DeepSeek V3 (OpenRouter)",
     "env": ("OPENROUTER_API_KEY",), "model_env": "ATLAS_DEEPSEEK_MODEL", "default_model": "deepseek/deepseek-chat",
     "url_env": "ATLAS_OPENROUTER_URL", "default_url": _OPENROUTER_URL, "free": False, "context_window": 65536},
    {"id": "cloud:grok", "provider": "grok", "label": "☁ xAI Grok 3 Mini",
     "env": ("XAI_API_KEY", "GROK_API_KEY"), "model_env": "ATLAS_GROK_MODEL", "default_model": "grok-3-mini",
     "url_env": "ATLAS_GROK_URL", "default_url": _GROK_URL, "free": False, "context_window": 131072},
    {"id": "cloud:openai", "provider": "openai", "label": "☁ OpenAI GPT-4.1 Mini",
     "env": ("OPENAI_API_KEY",), "model_env": "ATLAS_OPENAI_MODEL", "default_model": "gpt-4.1-mini",
     "url_env": "ATLAS_OPENAI_URL", "default_url": _OPENAI_URL, "free": False, "context_window": 131072},
    {"id": "cloud:anthropic", "provider": "anthropic", "label": "☁ Anthropic Claude Sonnet 4",
     "env": ("ANTHROPIC_API_KEY",), "model_env": "ATLAS_ANTHROPIC_MODEL", "default_model": "claude-sonnet-4-20250514",
     "url_env": "ATLAS_ANTHROPIC_URL", "default_url": _ANTHROPIC_URL, "free": False, "context_window": 200000},
)
_CLOUD_BY_ID = {m["id"]: m for m in CLOUD_MODELS}


def _url(name, default):  # test hook: point at a local stub server ("{model}" in the value is filled in)
    return (os.environ.get(name) or default).replace("{model}", GEMINI_CURRENT.get("model", ""))


GEMINI_CURRENT = {}  # the model being tried now; only used to fill "{model}" in the test hook


class CloudError(RuntimeError):
    """A cloud call that ended with an HTTP error. .code holds the status; the message holds no key."""

    def __init__(self, message, code=None, network=False):
        super().__init__(message)
        self.code = code
        self.network = network  # no answer at all (timeout, connection dropped): worth one more try


def enabled():
    return os.environ.get("ATLAS_CLOUD_SWARM", "1").strip().lower() not in ("0", "false", "no", "off")


def available(provider):
    if not enabled() or provider not in PROVIDERS:
        return False
    if provider == "github":
        return bool(os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_MODELS_KEY", "").strip())
    return bool(os.environ.get(PROVIDERS[provider][1], "").strip())


def label(provider):
    return PROVIDERS[provider][0] if provider in PROVIDERS else str(provider)


def model_name(provider):
    """The cloud model this provider uses now (or tries first). Shown in the UI; holds no key."""
    if provider == "gemini":
        return GEMINI_CURRENT.get("model") or GEMINI_MODEL.split(",")[0].strip()
    if provider == "deepseek":
        return DEEPSEEK_MODEL
    if provider == "groq":
        return os.environ.get("ATLAS_GROQ_MODEL", "llama-3.3-70b-versatile")
    if provider == "cerebras":
        return os.environ.get("ATLAS_CEREBRAS_MODEL", "llama-3.3-70b")
    if provider == "openrouter":
        return os.environ.get("ATLAS_OPENROUTER_FREE_MODEL", "openrouter/free")
    if provider == "mistral":
        return os.environ.get("ATLAS_MISTRAL_MODEL", "mistral-small-latest")
    if provider == "github":
        return os.environ.get("ATLAS_GITHUB_MODEL", "gpt-4o-mini")
    if provider == "abliterated":
        return os.environ.get("ATLAS_ABLITERATED_CLOUD_MODEL", "nousresearch/hermes-3-llama-3.1-405b:free")
    return ""


def free_providers():
    """List of all free tier providers that currently have active keys."""
    return [p for p in ("gemini", "groq", "cerebras", "openrouter", "mistral", "github") if available(p)]


def any_free_available():
    return bool(free_providers() or available("deepseek"))


def status():
    """Cloud readiness for the UI: on/off, and for each provider whether a key is set. Never returns a key."""
    return {"enabled": enabled(), "providers": {p: {"label": v[0], "key": bool(os.environ.get(v[1], "").strip()),
                                                     "model": model_name(p)} for p, v in PROVIDERS.items()}}


def _opener():
    """ATLAS_CLOUD_PROXY (for example http://127.0.0.1:7897) sends ONLY the cloud calls through that proxy.
    Without it Python uses its normal rules: the HTTPS_PROXY variable, then the Windows system proxy. A proxy
    program that is not set as the Windows system proxy (Clash and similar) is not seen by Python, so calls hang."""
    proxy = os.environ.get("ATLAS_CLOUD_PROXY", "").strip()
    if proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()


def _post(url, headers, payload, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with _opener().open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # the body is not echoed
        raise CloudError(f"cloud model returned HTTP {exc.code}", exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        timed_out = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
        hint = "" if timed_out or os.environ.get("ATLAS_CLOUD_PROXY", "").strip() else " (behind a proxy? set ATLAS_CLOUD_PROXY)"
        raise CloudError(f"cloud model not reachable: {type(exc).__name__}{hint}", None, True) from exc


def _gemini_models():
    return [m.strip() for m in GEMINI_MODEL.split(",") if m.strip()]


def _gemini_config(temperature, max_tokens, model=None):
    """Gemini Flash counts its hidden thinking tokens inside maxOutputTokens, so a small limit can leave
    no room for the visible answer. Flash can turn thinking off (budget 0); other models keep their default."""
    cfg = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if "flash" in (model or GEMINI_MODEL).lower():
        cfg["thinkingConfig"] = {"thinkingBudget": 0}
    return cfg


def _openrouter_why(data):
    """A short reason (no key, no prompt text) for an OpenRouter reply that has no answer."""
    try:
        err = data.get("error")
        if isinstance(err, dict):
            return f" (provider error {err.get('code', '?')}: {str(err.get('message', ''))[:120]})"
        reason = (data.get("choices") or [{}])[0].get("finish_reason")
        if reason:
            return f" (finish reason: {reason})"
    except (AttributeError, IndexError, TypeError):
        pass
    return ""


def _gemini_why(data):
    """A short reason (no key, no prompt text) for an empty Gemini answer."""
    try:
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            return f" (prompt blocked: {block})"
        reason = (data.get("candidates") or [{}])[0].get("finishReason")
        if reason:
            return f" (finish reason: {reason})"
    except (AttributeError, IndexError, TypeError):
        pass
    return ""


def _gemini_post(key, model, prompt, temperature, max_tokens, timeout):
    GEMINI_CURRENT["model"] = model
    cfg = _gemini_config(temperature, max_tokens, model)
    url = _url("ATLAS_GEMINI_URL", _GEMINI_URL.format(model=model))
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": cfg}
    try:
        return _post(url, {"x-goog-api-key": key}, body, timeout)
    except CloudError as exc:
        if exc.code == 400 and "thinkingConfig" in cfg:  # some models refuse "thinking off": ask again without it
            cfg.pop("thinkingConfig")
            return _post(url, {"x-goog-api-key": key}, body, timeout)
        raise


def _gemini_call(key, prompt, temperature, max_tokens, timeout):
    """Try each Gemini model in order. Busy answers and stalled connections are retried; a missing model moves on.
    The whole call is capped (GEMINI_BUDGET_SECONDS) so a bad network never holds a bot for minutes."""
    models, last, tried = _gemini_models(), None, []
    started = time.monotonic()
    for model in models:
        tried.append(model)
        for attempt in range(len(RETRY_WAITS) + 1):
            left = GEMINI_BUDGET_SECONDS - (time.monotonic() - started)
            if left <= 1:
                raise CloudError(f"{last or 'cloud model not reachable'} (gave up after {GEMINI_BUDGET_SECONDS} s; tried {', '.join(tried)})",
                                 getattr(last, "code", None), True)
            try:
                data = _gemini_post(key, model, prompt, temperature, max_tokens, min(timeout, GEMINI_ATTEMPT_SECONDS, left))
            except CloudError as exc:
                last = exc
                if exc.code in (401, 403):  # the key is wrong or refused: other models will not help
                    raise
                if (exc.code in RETRY_CODES or exc.network) and attempt < len(RETRY_WAITS):
                    time.sleep(RETRY_WAITS[attempt])
                    continue
                break  # 404 and other errors, or no tries left: next model
            try:
                text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
            except (KeyError, IndexError, TypeError):
                text = ""
            if not text:  # say WHY: a spent token budget and a safety block need different fixes
                raise RuntimeError("Gemini sent back no text" + _gemini_why(data))
            return text
    if last is None:
        raise RuntimeError("no Gemini model is set")
    raise CloudError(f"{last} (tried {', '.join(tried)})", last.code, last.network)


def call(provider, prompt, temperature=0.3, max_tokens=900, timeout=120):
    """Return the model text. Raises RuntimeError with a short message that holds no key."""
    if not available(provider):
        raise RuntimeError(f"no key for {provider}")
    key = (os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_MODELS_KEY", "").strip()) if provider == "github" else os.environ[PROVIDERS[provider][1]].strip()
    if provider == "gemini":
        return _gemini_call(key, prompt, temperature, max_tokens, timeout)

    url = _url("ATLAS_OPENROUTER_URL", _OPENROUTER_URL)
    model = DEEPSEEK_MODEL
    if provider == "groq":
        url = _url("ATLAS_GROQ_URL", _GROQ_URL)
        model = os.environ.get("ATLAS_GROQ_MODEL", "llama-3.3-70b-versatile")
    elif provider == "cerebras":
        url = _url("ATLAS_CEREBRAS_URL", _CEREBRAS_URL)
        model = os.environ.get("ATLAS_CEREBRAS_MODEL", "llama-3.3-70b")
    elif provider == "openrouter":
        url = _url("ATLAS_OPENROUTER_URL", _OPENROUTER_URL)
        model = os.environ.get("ATLAS_OPENROUTER_FREE_MODEL", "openrouter/free")
    elif provider == "mistral":
        url = _url("ATLAS_MISTRAL_URL", _MISTRAL_URL)
        model = os.environ.get("ATLAS_MISTRAL_MODEL", "mistral-small-latest")
    elif provider == "github":
        url = _url("ATLAS_GITHUB_URL", _GITHUB_URL)
        model = os.environ.get("ATLAS_GITHUB_MODEL", "gpt-4o-mini")
    elif provider == "abliterated":
        url = _url("ATLAS_OPENROUTER_URL", _OPENROUTER_URL)
        model = os.environ.get("ATLAS_ABLITERATED_CLOUD_MODEL", "nousresearch/hermes-3-llama-3.1-405b:free")

    headers = {"Authorization": f"Bearer {key}"}
    if provider in ("openrouter", "abliterated"):
        headers["HTTP-Referer"] = "https://github.com/atlas-chat"
        headers["X-Title"] = "Atlas Chat Hyperswarm"
    data = _post(url, headers,
                 {"model": model, "messages": [{"role": "user", "content": prompt}],
                  "temperature": temperature, "max_tokens": max_tokens}, timeout)
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"{label(provider)} sent back no text" + _openrouter_why(data))


def _entry_key(entry):
    for env_name in entry["env"]:
        val = os.environ.get(env_name, "").strip()
        if val:
            return val
    return ""


def _entry_model(entry):
    if entry["provider"] == "gemini":
        return model_name("gemini")
    raw = os.environ.get(entry["model_env"], "").strip()
    return raw.split(",")[0].strip() if raw else entry["default_model"]


def is_cloud_model(model_id):
    return isinstance(model_id, str) and model_id in _CLOUD_BY_ID


def context_window(model_id):
    entry = _CLOUD_BY_ID.get(str(model_id or ""))
    return int(entry["context_window"]) if entry else 65536


def picker_models():
    """Return cloud models for the UI picker. Never returns a key value."""
    on = enabled()
    return [
        {
            "id": m["id"],
            "provider": m["provider"],
            "label": m["label"],
            "model": _entry_model(m),
            "env": m["env"][0],
            "free": m["free"],
            "ready": bool(on and _entry_key(m)),
            "context_window": m["context_window"],
        }
        for m in CLOUD_MODELS
    ]


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _clean_messages(messages):
    out = []
    for m in messages if isinstance(messages, list) else []:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "user")
        if role not in ("system", "user", "assistant"):
            role = "user"
        text = _text_of(m.get("content")).strip()
        if text:
            out.append({"role": role, "content": text})
    return out or [{"role": "user", "content": "Hello"}]


def _flatten_prompt(messages):
    parts = []
    for m in _clean_messages(messages):
        tag = "System" if m["role"] == "system" else ("Assistant" if m["role"] == "assistant" else "User")
        parts.append(f"{tag}:\n{m['content']}")
    return "\n\n".join(parts)


def chat_completion(request, timeout=120):
    """Run a chat completion on a cloud model from the picker. Returns (completion_dict, machine_label)."""
    model_id = str((request or {}).get("model") or "")
    entry = _CLOUD_BY_ID.get(model_id)
    if not entry:
        raise CloudError(f"Unknown cloud model: {model_id}", 400)
    if not enabled():
        raise CloudError("Cloud models are turned off (ATLAS_CLOUD_SWARM=0).", 403)
    key = _entry_key(entry)
    if not key:
        env_hint = " or ".join(entry["env"])
        raise CloudError(f"No API key for {entry['label']}. Set {env_hint} in your environment and restart Atlas Chat.", 401)
    temperature = float(request.get("temperature", 0.4))
    max_tokens = int(request.get("max_tokens") or 2048)
    if max_tokens < 64:
        max_tokens = 2048
    messages = _clean_messages(request.get("messages"))
    upstream_model = _entry_model(entry)

    if entry["provider"] == "gemini":
        text = _gemini_call(key, _flatten_prompt(messages), temperature, max_tokens, timeout)
    elif entry["provider"] == "anthropic":
        sys_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_msgs = [m for m in messages if m["role"] in ("user", "assistant")] or [{"role": "user", "content": "Hello"}]
        payload = {"model": upstream_model, "max_tokens": max_tokens, "temperature": temperature, "messages": chat_msgs}
        if sys_parts:
            payload["system"] = "\n\n".join(sys_parts)
        data = _post(_url(entry["url_env"], entry["default_url"]),
                     {"x-api-key": key, "anthropic-version": "2023-06-01"}, payload, timeout)
        try:
            text = "".join(b.get("text", "") for b in (data.get("content") or []) if isinstance(b, dict)).strip()
        except (TypeError, KeyError):
            text = ""
        if not text:
            raise RuntimeError(f"{entry['label']} sent back no text")
    else:
        data = _post(_url(entry["url_env"], entry["default_url"]),
                     {"Authorization": f"Bearer {key}"},
                     {"model": upstream_model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                     timeout)
        try:
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            text = ""
        if not text:
            raise RuntimeError(f"{entry['label']} sent back no text" + _openrouter_why(data))

    prompt_est = max(1, sum(len(m["content"]) for m in messages) // 4)
    comp_est = max(1, len(text) // 4)
    completion = {
        "id": f"cloud-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_est, "completion_tokens": comp_est, "total_tokens": prompt_est + comp_est},
    }
    return completion, f"Cloud ({entry['provider'].upper()} · {upstream_model})"
