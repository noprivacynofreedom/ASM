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
PROVIDERS = {"gemini": ("Gemini", "GEMINI_API_KEY"), "deepseek": ("DeepSeek", "OPENROUTER_API_KEY")}


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
    return enabled() and provider in PROVIDERS and bool(os.environ.get(PROVIDERS[provider][1], "").strip())


def label(provider):
    return PROVIDERS[provider][0]


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
    key = os.environ[PROVIDERS[provider][1]].strip()
    if provider == "gemini":
        return _gemini_call(key, prompt, temperature, max_tokens, timeout)
    data = _post(_url("ATLAS_OPENROUTER_URL", _OPENROUTER_URL), {"Authorization": f"Bearer {key}"},
                 {"model": DEEPSEEK_MODEL, "messages": [{"role": "user", "content": prompt}],
                  "temperature": temperature, "max_tokens": max_tokens}, timeout)
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("DeepSeek sent back no text" + _openrouter_why(data))
