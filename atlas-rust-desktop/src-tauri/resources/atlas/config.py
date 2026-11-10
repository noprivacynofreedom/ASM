"""Atlas Chat-local configuration.

This module deliberately has no imports from the sibling Atlas application.
All paths are rooted in this project directory unless explicitly configured.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / "settings.json"

_DEFAULTS: dict[str, Any] = {
    "server_port": 8090,
    "upstream_host": "127.0.0.1",
    "upstream_port": 8080,
    "data_file": "data.json",
    "llama_swap_exe": "",
    "llama_swap_config": "",
    "llm_model": "coder",
    "llm_timeout": 180,
    "llm_temperature": 0.7,
    "llm_max_tokens": 2048,
    "workspace_dir": "workspace",
}

def load_settings(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load Atlas Chat's settings.json, retaining safe defaults for missing keys."""
    settings = dict(_DEFAULTS)
    source = Path(path) if path else SETTINGS_FILE
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            settings.update(raw)
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read Atlas Chat settings at {source}: {exc}") from exc

    # Validate the connection values instead of silently accepting bad strings.
    settings["upstream_host"] = str(settings.get("upstream_host") or "127.0.0.1")
    settings["upstream_port"] = int(settings.get("upstream_port", 8080))
    settings["llm_timeout"] = max(1, int(settings.get("llm_timeout", 180)))
    settings["llm_max_tokens"] = max(1, int(settings.get("llm_max_tokens", 2048)))
    settings["llm_temperature"] = float(settings.get("llm_temperature", 0.7))
    return settings

SETTINGS = load_settings()
ATLAS_HOST = "127.0.0.1"
WORKSPACE_DIR = Path(os.environ.get("ATLAS_CHAT_WORKSPACE", BASE_DIR / SETTINGS["workspace_dir"]))
if not WORKSPACE_DIR.is_absolute():
    WORKSPACE_DIR = (BASE_DIR / WORKSPACE_DIR).resolve()
else:
    WORKSPACE_DIR = WORKSPACE_DIR.resolve()

def get_setting(name: str, default: Any = None) -> Any:
    """Read a setting from the Atlas Chat-local settings snapshot."""
    return SETTINGS.get(name, default)
