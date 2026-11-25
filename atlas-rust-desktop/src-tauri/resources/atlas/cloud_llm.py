"""Optional cloud models for /swarm and chat: Gemini, Vertex AI, OpenRouter, Groq, Cerebras, Mistral, GitHub, etc.

No extra packages: plain urllib, so it works in the bundled Python.
Keys come from the local Cloud Keys settings panel (DATA_DIR/.atlas/cloud_keys.json) or environment variables:
  GEMINI_API_KEY, VERTEX_API_KEY (or GOOGLE_CLOUD_API_KEY), OPENROUTER_API_KEY, GROQ_API_KEY, etc.
Set ATLAS_CLOUD_SWARM=0 to turn cloud off.
Gemini & Vertex: ATLAS_GEMINI_MODEL / ATLAS_VERTEX_MODEL take one model name or a comma list, tried in order.
Dynamic switching: tracks live health/latency per provider and routes to whichever configured key is live.
ATLAS_CLOUD_PROXY=http://host:port sends only the cloud calls through a proxy.
"""
from __future__ import annotations
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request

# Google retires Gemini models without much warning (gemini-2.5-flash answers 404 for new users), so keep a list.
GEMINI_MODEL = os.environ.get("ATLAS_GEMINI_MODEL", "gemini-3.8-flash,gemini-3.7-flash,gemini-flash-latest")
VERTEX_MODEL = os.environ.get("ATLAS_VERTEX_MODEL", "gemini-3.8-flash,gemini-3.7-flash,gemini-2.5-flash")
RETRY_CODES = (429, 500, 502, 503, 504)  # busy or broken for a moment: try the same model again
RETRY_WAITS = (2, 5)  # seconds to wait before the 2nd and the 3rd try
GEMINI_ATTEMPT_SECONDS = 45  # one try gets this long. A stalled connection is dropped and tried again.
GEMINI_BUDGET_SECONDS = 100  # all tries together; after this the swarm uses the next live key or local model
DEEPSEEK_MODEL = os.environ.get("ATLAS_DEEPSEEK_MODEL", "deepseek/deepseek-chat")
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_VERTEX_URL = "https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent"
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
    "vertex": ("Vertex AI", "VERTEX_API_KEY"),
    "deepseek": ("DeepSeek", "OPENROUTER_API_KEY"),
    "groq": ("Groq", "GROQ_API_KEY"),
    "cerebras": ("Cerebras", "CEREBRAS_API_KEY"),
    "openrouter": ("OpenRouter Free", "OPENROUTER_API_KEY"),
    "mistral": ("Mistral", "MISTRAL_API_KEY"),
    "github": ("GitHub Models", "GITHUB_TOKEN"),
    "grok": ("xAI Grok", "XAI_API_KEY"),
    "openai": ("OpenAI", "OPENAI_API_KEY"),
    "anthropic": ("Anthropic", "ANTHROPIC_API_KEY"),
    "abliterated": ("Abliterated Cloud", "OPENROUTER_API_KEY"),
}

# Settings-panel editable provider registry (order shown in UI).
PROVIDER_SPECS = (
    {"id": "vertex", "label": "Vertex AI (Agent Platform Express)", "short": "Vertex AI", "family": "google",
     "env": ("VERTEX_API_KEY", "GOOGLE_CLOUD_API_KEY"), "model_env": "ATLAS_VERTEX_MODEL",
     "default_model": "gemini-3.8-flash,gemini-3.7-flash,gemini-2.5-flash",
     "url_env": "ATLAS_VERTEX_URL", "default_url": _VERTEX_URL, "free": True, "protocol": "google"},
    {"id": "gemini", "label": "Gemini (Google AI Studio)", "short": "Gemini", "family": "google",
     "env": ("GEMINI_API_KEY",), "model_env": "ATLAS_GEMINI_MODEL",
     "default_model": "gemini-3.8-flash,gemini-3.7-flash,gemini-flash-latest",
     "url_env": "ATLAS_GEMINI_URL", "default_url": _GEMINI_URL, "free": True, "protocol": "google"},
    {"id": "openrouter", "label": "OpenRouter (Free / DeepSeek)", "short": "OpenRouter", "family": "openrouter",
     "env": ("OPENROUTER_API_KEY",), "model_env": "ATLAS_OPENROUTER_FREE_MODEL",
     "default_model": "openrouter/free",
     "url_env": "ATLAS_OPENROUTER_URL", "default_url": _OPENROUTER_URL, "free": True, "protocol": "openai"},
    {"id": "groq", "label": "Groq (Llama 3.3 70B)", "short": "Groq", "family": "groq",
     "env": ("GROQ_API_KEY",), "model_env": "ATLAS_GROQ_MODEL",
     "default_model": "llama-3.3-70b-versatile",
     "url_env": "ATLAS_GROQ_URL", "default_url": _GROQ_URL, "free": True, "protocol": "openai"},
    {"id": "cerebras", "label": "Cerebras (Llama 3.3 70B)", "short": "Cerebras", "family": "cerebras",
     "env": ("CEREBRAS_API_KEY",), "model_env": "ATLAS_CEREBRAS_MODEL",
     "default_model": "llama-3.3-70b",
     "url_env": "ATLAS_CEREBRAS_URL", "default_url": _CEREBRAS_URL, "free": True, "protocol": "openai"},
    {"id": "mistral", "label": "Mistral", "short": "Mistral", "family": "mistral",
     "env": ("MISTRAL_API_KEY",), "model_env": "ATLAS_MISTRAL_MODEL",
     "default_model": "mistral-small-latest",
     "url_env": "ATLAS_MISTRAL_URL", "default_url": _MISTRAL_URL, "free": True, "protocol": "openai"},
    {"id": "github", "label": "GitHub Models", "short": "GitHub Models", "family": "github",
     "env": ("GITHUB_TOKEN", "GH_MODELS_KEY"), "model_env": "ATLAS_GITHUB_MODEL",
     "default_model": "gpt-4o-mini",
     "url_env": "ATLAS_GITHUB_URL", "default_url": _GITHUB_URL, "free": True, "protocol": "openai"},
    {"id": "openai", "label": "OpenAI (or OpenAI-Compatible)", "short": "OpenAI", "family": "openai",
     "env": ("OPENAI_API_KEY",), "model_env": "ATLAS_OPENAI_MODEL",
     "default_model": "gpt-4.1-mini",
     "url_env": "ATLAS_OPENAI_URL", "default_url": _OPENAI_URL, "free": False, "protocol": "openai"},
    {"id": "anthropic", "label": "Anthropic Claude", "short": "Anthropic", "family": "anthropic",
     "env": ("ANTHROPIC_API_KEY",), "model_env": "ATLAS_ANTHROPIC_MODEL",
     "default_model": "claude-sonnet-4-20250514",
     "url_env": "ATLAS_ANTHROPIC_URL", "default_url": _ANTHROPIC_URL, "free": False, "protocol": "anthropic"},
    {"id": "grok", "label": "xAI Grok", "short": "xAI Grok", "family": "grok",
     "env": ("XAI_API_KEY", "GROK_API_KEY"), "model_env": "ATLAS_GROK_MODEL",
     "default_model": "grok-3-mini",
     "url_env": "ATLAS_GROK_URL", "default_url": _GROK_URL, "free": False, "protocol": "openai"},
)
_SPEC_BY_ID = {s["id"]: s for s in PROVIDER_SPECS}
# Aliases that share a backing key with another spec (deepseek & abliterated use openrouter's key).
_KEY_ALIAS = {"deepseek": "openrouter", "abliterated": "openrouter"}

# Cloud model picker entries.
CLOUD_MODELS = (
    {"id": "cloud:auto", "provider": "auto", "label": "☁ Auto (Best Live Cloud Key)",
     "env": ("VERTEX_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY"),
     "model_env": "", "default_model": "auto-live",
     "url_env": "", "default_url": "", "free": True, "context_window": 131072},
    {"id": "cloud:vertex", "provider": "vertex", "label": "☁ Vertex AI Gemini (Agent Platform)",
     "env": ("VERTEX_API_KEY", "GOOGLE_CLOUD_API_KEY"), "model_env": "ATLAS_VERTEX_MODEL", "default_model": "gemini-3.8-flash",
     "url_env": "ATLAS_VERTEX_URL", "default_url": _VERTEX_URL, "free": True, "context_window": 131072},
    {"id": "cloud:gemini", "provider": "gemini", "label": "☁ Gemini Flash (Google AI Studio)",
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


# ---------- Local Cloud Keys settings store (DATA_DIR/.atlas/cloud_keys.json) ----------
_KEYS_LOCK = threading.Lock()
_KEYS_PATH = ""  # configured by server.py or ATLAS_CLOUD_KEYS_FILE


def configure_keys_path(path):
    """Set the local file path used to persist user-entered cloud keys from the Settings panel."""
    global _KEYS_PATH
    with _KEYS_LOCK:
        _KEYS_PATH = str(path or "").strip()


def _keys_path():
    env_override = os.environ.get("ATLAS_CLOUD_KEYS_FILE")
    if env_override is not None:
        v = env_override.strip()
        return "" if v.lower() in ("", "0", "none", "off", "false") else v
    return _KEYS_PATH


def _empty_store():
    return {"cloud_enabled": True, "swarm_offload": False, "providers": {}}


def _load_store():
    path = _keys_path()
    if not path:
        return _empty_store()
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return _empty_store()
        providers = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
        return {
            "cloud_enabled": bool(raw.get("cloud_enabled", True)),
            "swarm_offload": bool(raw.get("swarm_offload", False)),
            "providers": providers,
        }
    except (OSError, ValueError):
        return _empty_store()


def _write_store(data):
    path = _keys_path()
    if not path:
        raise ValueError("Cloud keys storage path is not configured.")
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cloud_keys.", suffix=".tmp", dir=folder or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _provider_cfg(provider, store=None):
    base = _KEY_ALIAS.get(provider, provider)
    st = store if store is not None else _load_store()
    cfg = st.get("providers", {}).get(base)
    return cfg if isinstance(cfg, dict) else {}


def _mask_key(key):
    k = str(key or "").strip()
    if not k:
        return ""
    if len(k) >= 8:
        return "••••" + k[-4:]
    return "••••"


def _resolve_key(provider, store=None):
    """Return (key_value, source) where source is 'settings', 'env', or 'none'."""
    base = _KEY_ALIAS.get(provider, provider)
    cfg = _provider_cfg(base, store)
    if cfg.get("enabled") is False:
        return "", "disabled"
    saved = str(cfg.get("api_key") or "").strip()
    if saved:
        return saved, "settings"
    spec = _SPEC_BY_ID.get(base)
    env_names = spec["env"] if spec else ((PROVIDERS[provider][1],) if provider in PROVIDERS else ())
    for env_name in env_names:
        val = os.environ.get(env_name, "").strip()
        if val:
            return val, "env"
    return "", "none"


def _resolve_url(provider, url_env, default_url, store=None):
    base = _KEY_ALIAS.get(provider, provider)
    cfg = _provider_cfg(base, store)
    saved = str(cfg.get("url") or "").strip()
    raw = saved or (os.environ.get(url_env) if url_env else "") or default_url
    return raw.replace("{model}", GEMINI_CURRENT.get("model", ""))


# ---------- Dynamic live health tracking ----------
_HEALTH_LOCK = threading.Lock()
_HEALTH: dict[str, dict] = {}
COOLDOWN_TRANSIENT_SECONDS = 60.0
COOLDOWN_AUTH_SECONDS = 300.0


def _sanitize_error(msg, key=""):
    text = str(msg or "").strip()
    if key and key in text:
        text = text.replace(key, "[redacted]")
    return text[:200]


def record_success(provider, latency_ms=None, model=""):
    now = time.time()
    with _HEALTH_LOCK:
        _HEALTH[provider] = {
            "state": "live",
            "last_ok": now,
            "last_err": 0.0,
            "last_error": "",
            "last_code": 200,
            "latency_ms": round(float(latency_ms), 1) if latency_ms is not None else None,
            "model": str(model or ""),
            "cooldown_until": 0.0,
        }


def record_failure(provider, code=None, error="", network=False, key=""):
    now = time.time()
    cool = COOLDOWN_AUTH_SECONDS if code in (401, 403) else COOLDOWN_TRANSIENT_SECONDS
    with _HEALTH_LOCK:
        prev = _HEALTH.get(provider) or {}
        _HEALTH[provider] = {
            "state": "down",
            "last_ok": prev.get("last_ok", 0.0),
            "last_err": now,
            "last_error": _sanitize_error(error, key),
            "last_code": code,
            "latency_ms": prev.get("latency_ms"),
            "model": prev.get("model", ""),
            "cooldown_until": time.monotonic() + cool,
        }


def reset_health(provider=None):
    with _HEALTH_LOCK:
        if provider:
            _HEALTH.pop(provider, None)
        else:
            _HEALTH.clear()


def _in_cooldown(provider):
    with _HEALTH_LOCK:
        h = _HEALTH.get(provider)
        if not h:
            return False
        return float(h.get("cooldown_until") or 0.0) > time.monotonic()


def health_info(provider):
    with _HEALTH_LOCK:
        h = dict(_HEALTH.get(provider) or {})
    cool_left = max(0.0, float(h.get("cooldown_until") or 0.0) - time.monotonic())
    state = h.get("state") or "unknown"
    if state == "down" and cool_left <= 0:
        state = "degraded"
    return {
        "state": state,
        "latency_ms": h.get("latency_ms"),
        "last_error": h.get("last_error") or "",
        "last_code": h.get("last_code"),
        "cooldown_remaining": round(cool_left, 1),
        "last_ok": h.get("last_ok") or 0.0,
    }


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
    env_val = os.environ.get("ATLAS_CLOUD_SWARM")
    if env_val is not None and env_val.strip() != "":
        return env_val.strip().lower() not in ("0", "false", "no", "off")
    return bool(_load_store().get("cloud_enabled", True))


def swarm_offload_enabled():
    """When True, /swarm offloads bot subtasks in parallel across all live configured cloud keys."""
    if not enabled():
        return False
    env_val = os.environ.get("ATLAS_SWARM_CLOUD_OFFLOAD")
    if env_val is not None and env_val.strip() != "":
        return env_val.strip().lower() in ("1", "true", "yes", "on")
    return bool(_load_store().get("swarm_offload", False))


def available(provider):
    if not enabled():
        return False
    if provider == "auto":
        return bool(all_available_providers())
    if provider not in PROVIDERS:
        return False
    key, _src = _resolve_key(provider)
    return bool(key)


def label(provider):
    if provider == "auto":
        return "Auto Cloud"
    return PROVIDERS[provider][0] if provider in PROVIDERS else str(provider)


def _google_models(provider):
    cfg = _provider_cfg(provider)
    saved = str(cfg.get("model") or "").strip()
    if saved:
        raw = saved
    elif provider == "vertex":
        raw = os.environ.get("ATLAS_VERTEX_MODEL", VERTEX_MODEL)
    else:
        raw = os.environ.get("ATLAS_GEMINI_MODEL", GEMINI_MODEL)
    return [m.strip() for m in raw.split(",") if m.strip()]


def model_name(provider):
    """The cloud model this provider uses now (or tries first). Shown in the UI; holds no key."""
    if provider == "auto":
        cands = live_providers()
        return f"auto ({label(cands[0])})" if cands else "auto"
    if provider in ("gemini", "vertex"):
        models = _google_models(provider)
        if provider == "gemini" and GEMINI_CURRENT.get("provider") == "gemini" and GEMINI_CURRENT.get("model"):
            return GEMINI_CURRENT["model"]
        if provider == "vertex" and GEMINI_CURRENT.get("provider") == "vertex" and GEMINI_CURRENT.get("model"):
            return GEMINI_CURRENT["model"]
        return models[0] if models else ("gemini-3.8-flash")
    if provider == "deepseek":
        return os.environ.get("ATLAS_DEEPSEEK_MODEL", DEEPSEEK_MODEL)
    if provider == "abliterated":
        return os.environ.get("ATLAS_ABLITERATED_CLOUD_MODEL", "nousresearch/hermes-3-llama-3.1-405b:free")
    spec = _SPEC_BY_ID.get(provider)
    if spec:
        cfg = _provider_cfg(provider)
        saved = str(cfg.get("model") or "").strip()
        if saved:
            return saved.split(",")[0].strip()
        env_m = os.environ.get(spec["model_env"], "").strip() if spec.get("model_env") else ""
        return env_m.split(",")[0].strip() if env_m else spec["default_model"].split(",")[0].strip()
    return ""


def free_providers():
    """List of all free-tier / express providers that currently have active keys."""
    return [p for p in ("vertex", "gemini", "groq", "cerebras", "openrouter", "mistral", "github") if available(p)]


def all_available_providers():
    """All configured, enabled providers (free + paid) in registry order."""
    return [s["id"] for s in PROVIDER_SPECS if available(s["id"])]


def any_free_available():
    return bool(all_available_providers() or available("deepseek"))


def live_providers(preferred=None, exclude=None, include_cooldown=False):
    """Return available providers ordered by live health & speed (never hardcoded to one provider).

    `preferred` may be a provider name or iterable of provider names to prioritize first.
    Within each tier, providers reporting 'live' come before 'unknown', sorted by lowest latency_ms.
    """
    if not enabled():
        return []
    excl = set(exclude or ())
    pref_list = []
    if isinstance(preferred, str):
        pref_list = [preferred] if preferred else []
    elif preferred:
        pref_list = [p for p in preferred if p]

    pool = []
    seen = set()
    for p in list(pref_list) + all_available_providers():
        if p in seen or p in excl or p == "auto":
            continue
        if available(p):
            seen.add(p)
            pool.append(p)

    pref_set = set(pref_list)

    def rank(p):
        h = health_info(p)
        cool = 1 if _in_cooldown(p) else 0
        is_pref = 0 if p in pref_set else 1
        state_rank = 0 if h["state"] == "live" else (1 if h["state"] == "unknown" else 2)
        lat = h["latency_ms"] if isinstance(h["latency_ms"], (int, float)) else 999999.0
        pref_idx = pref_list.index(p) if p in pref_list else 999
        return (cool, is_pref, state_rank, lat, pref_idx)

    ordered = sorted(pool, key=rank)
    if not include_cooldown:
        active = [p for p in ordered if not _in_cooldown(p)]
        return active if active else ordered
    return ordered


def family_candidates(provider, expand_all=False, exclude=None):
    """Resolve a requested provider to a dynamic ordered list of live candidates.

    - 'gemini', 'vertex', or 'google' dynamically switch between whichever of Gemini / Vertex is live.
    - When expand_all=True (or provider=='auto'), any other live configured provider is appended as fallback.
    """
    if not enabled():
        return []
    excl = set(exclude or ())
    if not provider or provider == "auto":
        return live_providers(exclude=excl)
    if provider in ("gemini", "vertex", "google"):
        pref = ("gemini", "vertex") if provider == "gemini" else (("vertex", "gemini") if provider == "vertex" else ("vertex", "gemini"))
        if expand_all:
            return live_providers(preferred=pref, exclude=excl)
        cands = [p for p in pref if p not in excl and available(p)]
        # Sort Google candidates by live status and latency so whichever is reporting live wins!
        return sorted(cands, key=lambda p: (
            1 if _in_cooldown(p) else 0,
            0 if health_info(p)["state"] == "live" else (1 if health_info(p)["state"] == "unknown" else 2),
            health_info(p)["latency_ms"] if isinstance(health_info(p)["latency_ms"], (int, float)) else 999999.0,
            pref.index(p),
        ))
    if expand_all:
        pref = (provider, "openrouter") if provider == "deepseek" else (provider,)
        return live_providers(preferred=pref, exclude=excl)
    return [provider] if (provider not in excl and available(provider)) else []


def status():
    """Cloud readiness for the UI: on/off, and for each provider whether a key is set + live state. Never returns a key."""
    store = _load_store()
    out = {}
    for p, v in PROVIDERS.items():
        key, src = _resolve_key(p, store)
        out[p] = {
            "label": v[0],
            "key": bool(key),
            "source": src,
            "model": model_name(p),
            "health": health_info(p),
        }
    return {"enabled": enabled(), "swarm_offload": swarm_offload_enabled(), "providers": out}


def keys_view():
    """Sanitized Cloud Keys view for the Settings panel (GET /api/cloud/keys). Never returns full keys."""
    store = _load_store()
    items = []
    live_count = 0
    ready_count = 0
    for spec in PROVIDER_SPECS:
        pid = spec["id"]
        cfg = _provider_cfg(pid, store)
        key, src = _resolve_key(pid, store)
        is_enabled = cfg.get("enabled", True) is not False
        h = health_info(pid)
        if key and is_enabled:
            ready_count += 1
            if h["state"] == "live":
                live_count += 1
        items.append({
            "id": pid,
            "label": spec["label"],
            "short": spec["short"],
            "family": spec["family"],
            "env": list(spec["env"]),
            "free": bool(spec["free"]),
            "enabled": is_enabled,
            "key_set": bool(key),
            "key_source": src,
            "key_hint": _mask_key(key) if src == "settings" else "",
            "model": str(cfg.get("model") or "").strip(),
            "active_model": model_name(pid),
            "default_model": spec["default_model"],
            "url": str(cfg.get("url") or "").strip(),
            "default_url": spec["default_url"],
            "health": h,
        })
    return {
        "cloud_enabled": enabled(),
        "swarm_offload": swarm_offload_enabled(),
        "ready_count": ready_count,
        "live_count": live_count,
        "providers": items,
    }


def save_keys(payload):
    """Save Cloud Keys & routing preferences from the Settings panel. Returns sanitized keys_view()."""
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object.")
    with _KEYS_LOCK:
        store = _load_store()
        if "cloud_enabled" in payload:
            store["cloud_enabled"] = bool(payload["cloud_enabled"])
        if "swarm_offload" in payload:
            store["swarm_offload"] = bool(payload["swarm_offload"])
        updates = payload.get("providers")
        if isinstance(updates, dict):
            provs = store.setdefault("providers", {})
            for pid, entry in updates.items():
                if pid not in _SPEC_BY_ID or not isinstance(entry, dict):
                    continue
                cur = dict(provs.get(pid) or {})
                changed = False
                if entry.get("clear_key"):
                    if cur.pop("api_key", None) is not None:
                        changed = True
                elif "api_key" in entry:
                    new_key = str(entry.get("api_key") or "").strip()
                    if new_key:
                        if cur.get("api_key") != new_key:
                            changed = True
                        cur["api_key"] = new_key
                if "enabled" in entry:
                    new_en = bool(entry["enabled"])
                    if cur.get("enabled", True) != new_en:
                        changed = True
                    cur["enabled"] = new_en
                if "model" in entry:
                    new_m = str(entry.get("model") or "").strip()[:200]
                    if cur.get("model", "") != new_m:
                        changed = True
                    if new_m:
                        cur["model"] = new_m
                    else:
                        cur.pop("model", None)
                if "url" in entry:
                    new_u = str(entry.get("url") or "").strip()[:400]
                    if new_u and not new_u.startswith(("http://", "https://")):
                        raise ValueError(f"Invalid URL for {pid}: must start with http:// or https://")
                    if cur.get("url", "") != new_u:
                        changed = True
                    if new_u:
                        cur["url"] = new_u
                    else:
                        cur.pop("url", None)
                provs[pid] = cur
                if changed:
                    reset_health(pid)
                    if pid == "openrouter":
                        reset_health("deepseek")
                        reset_health("abliterated")
        _write_store(store)
    return keys_view()


def _opener():
    """ATLAS_CLOUD_PROXY (for example http://127.0.0.1:7897) sends ONLY the cloud calls through that proxy.
    Without it Python uses its normal rules: the HTTPS_PROXY variable, then the Windows system proxy. A proxy
    program that is not set as the Windows system proxy (Clash and similar) is not seen by Python, so calls hang."""
    proxy = os.environ.get("ATLAS_CLOUD_PROXY", "").strip()
    if proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()


def _http_detail(exc):
    """The provider's own error message from an HTTP error body (quota, safety refusal, bad request),
    so the user sees WHY, not just a code. The body is the provider's text, never our API key."""
    try:
        raw = exc.read().decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return ""
    if not raw:
        return ""
    try:
        data = json.loads(raw)
        err = data.get("error") if isinstance(data, dict) else None
        msg = (err.get("message") or err.get("status")) if isinstance(err, dict) else (err if isinstance(err, str) else "")
        if not msg and isinstance(data, dict):
            msg = data.get("message") or ""
        msg = str(msg or raw).strip()
    except ValueError:
        msg = raw
    msg = re.sub(r"\s+", " ", msg)
    return ": " + msg[:500] if msg else ""


def _post(url, headers, payload, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with _opener().open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # include the provider's own reason (refusal, quota, bad request)
        raise CloudError(f"cloud model returned HTTP {exc.code}{_http_detail(exc)}", exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        timed_out = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
        hint = "" if timed_out or os.environ.get("ATLAS_CLOUD_PROXY", "").strip() else " (behind a proxy? set ATLAS_CLOUD_PROXY)"
        raise CloudError(f"cloud model not reachable: {type(exc).__name__}{hint}", None, True) from exc


def _gemini_models():
    return _google_models("gemini")


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


def _google_post(provider, key, model, prompt, temperature, max_tokens, timeout):
    GEMINI_CURRENT["provider"] = provider
    GEMINI_CURRENT["model"] = model
    cfg = _gemini_config(temperature, max_tokens, model)
    url_env = "ATLAS_VERTEX_URL" if provider == "vertex" else "ATLAS_GEMINI_URL"
    default_url = _VERTEX_URL if provider == "vertex" else _GEMINI_URL
    url = _resolve_url(provider, url_env, default_url.format(model=model))
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": cfg}
    try:
        return _post(url, {"x-goog-api-key": key}, body, timeout)
    except CloudError as exc:
        if exc.code == 400 and "thinkingConfig" in cfg:  # some models refuse "thinking off": ask again without it
            cfg.pop("thinkingConfig")
            return _post(url, {"x-goog-api-key": key}, body, timeout)
        raise


def _google_call(provider, key, prompt, temperature, max_tokens, timeout):
    """Try each Gemini/Vertex model in order. Busy answers and stalled connections are retried; a missing model moves on.
    The whole call is capped (GEMINI_BUDGET_SECONDS) so a bad network never holds a bot for minutes."""
    models, last, tried = _google_models(provider), None, []
    started = time.monotonic()
    for model in models:
        tried.append(model)
        for attempt in range(len(RETRY_WAITS) + 1):
            left = GEMINI_BUDGET_SECONDS - (time.monotonic() - started)
            if left <= 1:
                err = CloudError(f"{last or 'cloud model not reachable'} (gave up after {GEMINI_BUDGET_SECONDS} s; tried {', '.join(tried)})",
                                 getattr(last, "code", None), True)
                record_failure(provider, err.code, str(err), True, key)
                raise err
            t0 = time.monotonic()
            try:
                data = _google_post(provider, key, model, prompt, temperature, max_tokens, min(timeout, GEMINI_ATTEMPT_SECONDS, left))
            except CloudError as exc:
                last = exc
                if exc.code in (401, 403):  # the key is wrong or refused: other models will not help
                    record_failure(provider, exc.code, str(exc), exc.network, key)
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
                err = RuntimeError(f"{label(provider)} sent back no text" + _gemini_why(data))
                record_failure(provider, None, str(err), False, key)
                raise err
            record_success(provider, (time.monotonic() - t0) * 1000.0, model)
            return text
    if last is None:
        raise RuntimeError(f"no {label(provider)} model is set")
    record_failure(provider, last.code, str(last), last.network, key)
    raise CloudError(f"{last} (tried {', '.join(tried)})", last.code, last.network)


def _gemini_call(key, prompt, temperature, max_tokens, timeout):
    return _google_call("gemini", key, prompt, temperature, max_tokens, timeout)


def call(provider, prompt, temperature=0.3, max_tokens=900, timeout=120):
    """Return the model text. Raises RuntimeError with a short message that holds no key."""
    if provider == "auto":
        text, _used, _m = call_dynamic(prompt, preferred=None, temperature=temperature, max_tokens=max_tokens,
                                       timeout=timeout, expand_all=True)
        return text
    if not available(provider):
        raise RuntimeError(f"no key for {provider}")
    key, _src = _resolve_key(provider)
    if provider in ("gemini", "vertex"):
        return _google_call(provider, key, prompt, temperature, max_tokens, timeout)

    t0 = time.monotonic()
    if provider == "anthropic":
        url = _resolve_url("anthropic", "ATLAS_ANTHROPIC_URL", _ANTHROPIC_URL)
        model = model_name("anthropic")
        try:
            data = _post(url, {"x-api-key": key, "anthropic-version": "2023-06-01"},
                         {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                          "messages": [{"role": "user", "content": prompt}]}, timeout)
        except CloudError as exc:
            record_failure(provider, exc.code, str(exc), exc.network, key)
            raise
        try:
            text = "".join(b.get("text", "") for b in (data.get("content") or []) if isinstance(b, dict)).strip()
        except (TypeError, KeyError):
            text = ""
        if not text:
            record_failure(provider, None, "Anthropic sent back no text", False, key)
            raise RuntimeError("Anthropic sent back no text")
        record_success(provider, (time.monotonic() - t0) * 1000.0, model)
        return text

    spec = _SPEC_BY_ID.get(_KEY_ALIAS.get(provider, provider))
    url_env = spec["url_env"] if spec else "ATLAS_OPENROUTER_URL"
    default_url = spec["default_url"] if spec else _OPENROUTER_URL
    url = _resolve_url(provider, url_env, default_url)
    model = model_name(provider)

    headers = {"Authorization": f"Bearer {key}"}
    if provider in ("openrouter", "abliterated", "deepseek"):
        headers["HTTP-Referer"] = "https://github.com/atlas-chat"
        headers["X-Title"] = "Atlas Chat Hyperswarm"
    try:
        data = _post(url, headers,
                     {"model": model, "messages": [{"role": "user", "content": prompt}],
                      "temperature": temperature, "max_tokens": max_tokens}, timeout)
    except CloudError as exc:
        record_failure(provider, exc.code, str(exc), exc.network, key)
        raise
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        text = ""
    if not text:
        err = RuntimeError(f"{label(provider)} sent back no text" + _openrouter_why(data))
        record_failure(provider, None, str(err), False, key)
        raise err
    record_success(provider, (time.monotonic() - t0) * 1000.0, model)
    return text


def call_dynamic(prompt, preferred=None, temperature=0.3, max_tokens=900, timeout=120,
                 expand_all=False, exclude=None):
    """Call the best live configured cloud provider, dynamically failing over to the next live one.

    Returns (text, provider_id, model_name). Raises CloudError / RuntimeError if all candidates fail.
    """
    candidates = family_candidates(preferred, expand_all=expand_all, exclude=exclude)
    if not candidates:
        raise CloudError("No live cloud provider keys are configured.", 401)
    last_exc = None
    tried = []
    for prov in candidates:
        tried.append(prov)
        try:
            text = call(prov, prompt, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
            return text, prov, model_name(prov)
        except Exception as exc:
            last_exc = exc
            continue
    if isinstance(last_exc, CloudError):
        raise last_exc
    raise CloudError(f"{last_exc or 'All live cloud providers failed'} (tried {', '.join(tried)})",
                     getattr(last_exc, "code", None), getattr(last_exc, "network", False))


def probe(provider=None, timeout=12):
    """Actively test one provider (or all configured providers in parallel) to mark live/down + latency."""
    targets = [provider] if provider else all_available_providers()
    results = {}
    lock = threading.Lock()

    def _one(pid):
        if not available(pid):
            with lock:
                results[pid] = {"ok": False, "state": "nokey", "error": "No key configured"}
            return
        t0 = time.monotonic()
        try:
            old_waits = RETRY_WAITS
            # Use a tiny, fast liveness request (no long waits inside probe).
            call(pid, "Reply with OK.", temperature=0.0, max_tokens=8, timeout=timeout)
            ms = round((time.monotonic() - t0) * 1000.0, 1)
            with lock:
                results[pid] = {"ok": True, "state": "live", "latency_ms": ms, "model": model_name(pid)}
        except Exception as exc:
            with lock:
                results[pid] = {"ok": False, "state": "down", "error": str(exc)[:180], "code": getattr(exc, "code", None)}

    threads = [threading.Thread(target=_one, args=(pid,), daemon=True) for pid in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout + 5)
    return {"results": results, **keys_view()}


def _entry_key(entry):
    if entry["provider"] == "auto":
        return "auto" if all_available_providers() else ""
    key, _src = _resolve_key(entry["provider"])
    return key


def _entry_model(entry):
    if entry["provider"] in ("gemini", "vertex", "auto"):
        return model_name(entry["provider"])
    cfg = _provider_cfg(entry["provider"])
    saved = str(cfg.get("model") or "").strip()
    if saved and entry["id"] != "cloud:qwen-coder-free":
        return saved.split(",")[0].strip()
    raw = os.environ.get(entry["model_env"], "").strip() if entry.get("model_env") else ""
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
            "health": health_info(m["provider"]) if m["provider"] != "auto" else {"state": "live" if live_providers() else "unknown"},
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
        raise CloudError(f"No API key for {entry['label']}. Set {env_hint} or add it in Cloud Keys settings.", 401)
    temperature = float(request.get("temperature", 0.4))
    max_tokens = int(request.get("max_tokens") or 2048)
    if max_tokens < 64:
        max_tokens = 2048
    messages = _clean_messages(request.get("messages"))
    upstream_model = _entry_model(entry)
    used_provider = entry["provider"]

    if entry["provider"] == "auto":
        text, used_provider, upstream_model = call_dynamic(
            _flatten_prompt(messages), preferred=None, temperature=temperature,
            max_tokens=max_tokens, timeout=timeout, expand_all=True)
    elif entry["provider"] in ("gemini", "vertex"):
        # Dynamic Google switching: try preferred Google provider first, auto-switch to the other if live.
        text, used_provider, upstream_model = call_dynamic(
            _flatten_prompt(messages), preferred=entry["provider"], temperature=temperature,
            max_tokens=max_tokens, timeout=timeout, expand_all=False)
    elif entry["provider"] == "anthropic":
        sys_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_msgs = [m for m in messages if m["role"] in ("user", "assistant")] or [{"role": "user", "content": "Hello"}]
        payload = {"model": upstream_model, "max_tokens": max_tokens, "temperature": temperature, "messages": chat_msgs}
        if sys_parts:
            payload["system"] = "\n\n".join(sys_parts)
        t0 = time.monotonic()
        try:
            data = _post(_resolve_url("anthropic", entry["url_env"], entry["default_url"]),
                         {"x-api-key": key, "anthropic-version": "2023-06-01"}, payload, timeout)
        except CloudError as exc:
            record_failure("anthropic", exc.code, str(exc), exc.network, key)
            raise
        try:
            text = "".join(b.get("text", "") for b in (data.get("content") or []) if isinstance(b, dict)).strip()
        except (TypeError, KeyError):
            text = ""
        if not text:
            record_failure("anthropic", None, "Anthropic sent back no text", False, key)
            raise RuntimeError(f"{entry['label']} sent back no text")
        record_success("anthropic", (time.monotonic() - t0) * 1000.0, upstream_model)
    else:
        t0 = time.monotonic()
        try:
            data = _post(_resolve_url(entry["provider"], entry["url_env"], entry["default_url"]),
                         {"Authorization": f"Bearer {key}"},
                         {"model": upstream_model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                         timeout)
        except CloudError as exc:
            record_failure(entry["provider"], exc.code, str(exc), exc.network, key)
            raise
        try:
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            text = ""
        if not text:
            record_failure(entry["provider"], None, "empty reply", False, key)
            raise RuntimeError(f"{entry['label']} sent back no text" + _openrouter_why(data))
        record_success(entry["provider"], (time.monotonic() - t0) * 1000.0, upstream_model)

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
    return completion, f"Cloud ({used_provider.upper()} · {upstream_model})"
