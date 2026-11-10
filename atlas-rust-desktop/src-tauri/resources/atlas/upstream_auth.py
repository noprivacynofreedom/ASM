"""Optional bearer key for llama-swap when its config.yaml enables `apiKeys`.

Set "upstream_api_key" in settings.json (or the ATLAS_UPSTREAM_API_KEY environment
variable). Empty or missing means no Authorization header, which is the default and
matches a llama-swap without keys. The value is read once per process; restart Atlas
after changing it.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE = None


def _read_key():
    key = os.environ.get("ATLAS_UPSTREAM_API_KEY", "").strip()
    if key:
        return key
    for folder in (os.environ.get("ATLAS_DATA_DIR"), _HERE):
        if not folder:
            continue
        try:
            with open(os.path.join(folder, "settings.json"), encoding="utf-8") as handle:
                value = json.load(handle).get("upstream_api_key", "")
            if isinstance(value, str) and value.strip():
                return value.strip()
            return ""
        except (OSError, ValueError, AttributeError):
            continue
    return ""


def headers(base=None):
    """Return `base` plus an Authorization header when a key is configured."""
    global _CACHE
    if _CACHE is None:
        _CACHE = _read_key()
    merged = dict(base or {})
    if _CACHE:
        merged["Authorization"] = "Bearer " + _CACHE
    return merged
