"""Opt-in module registry for Atlas Chat.

Lets Odysseus-inspired and advanced workspace capabilities ship as optional,
zero-overhead modules controlled via ``settings.json`` under the ``modules``
key. Missing keys safely inherit defaults without overwriting unrelated user
settings or data files.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

_WRITE_LOCK = threading.Lock()

MODULE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "compare",
        "name": "Blind Compare Mode",
        "description": "Run a prompt across 2–4 local, LAN-peer, or cloud models side-by-side with masked labels, vote on the winner, and log local-vs-cloud speed & win-rate telemetry.",
        "category": "ai_core",
        "privacy": "Hybrid",
        "slash_command": "/compare",
        "default_enabled": True,
        "implemented": True,
    },
    {
        "id": "deep_research",
        "name": "Swarm Deep Research",
        "description": "Multi-step parallel web research pipeline built on Hyperswarm and web fetchers, producing cited reports with one-click export to Docs Canvas.",
        "category": "ai_core",
        "privacy": "Hybrid",
        "slash_command": "/research",
        "default_enabled": True,
        "implemented": True,
    },
    {
        "id": "cookbook",
        "name": "Hardware-Aware Model Cookbook",
        "description": "Hardware-aware model recommendations mapped to Atlas aliases (assist, coder, mentor, tasks, vision) and LAN compute peers, with safe pull commands.",
        "category": "models",
        "privacy": "Local",
        "slash_command": "/cookbook",
        "default_enabled": True,
        "implemented": True,
    },
    {
        "id": "skills_registry",
        "name": "Governed Skills Registry",
        "description": "Declarative reusable agent skills governed by Atlas MCP tool tiers, interactive write approvals, and diff-reviewed refinements.",
        "category": "agents",
        "privacy": "Local",
        "slash_command": "/skills-reg",
        "default_enabled": True,
        "implemented": True,
    },
    {
        "id": "docs_canvas",
        "name": "Writing-First Docs Canvas",
        "description": "Writing-first Markdown/HTML/CSV editor with reviewable AI edit proposals and unified diffs.",
        "category": "workspace",
        "privacy": "Local",
        "slash_command": "/docs",
        "default_enabled": True,
        "implemented": True,
    },
    {
        "id": "scheduler",
        "name": "Scheduled Agent Tasks",
        "description": "Cron/interval background agent jobs tracked in Operations with read-only defaults and explicit write capability grants.",
        "category": "agents",
        "privacy": "Local",
        "slash_command": "",
        "default_enabled": False,
        "implemented": True,
    },
    {
        "id": "productivity_mcp",
        "name": "Productivity MCP Packs (Email, CalDAV, Tasks)",
        "description": "Opt-in external MCP connectors for IMAP triage/drafts (send disabled by default), CalDAV calendar sync, and local tasks.",
        "category": "mcp_pack",
        "privacy": "External MCP",
        "slash_command": "",
        "default_enabled": False,
        "implemented": True,
    },
    {
        "id": "media_drawer",
        "name": "Media Gallery & Image MCP",
        "description": "Lightweight attachment gallery with optional pluggable local image-generation MCP connector.",
        "category": "workspace",
        "privacy": "Local",
        "slash_command": "",
        "default_enabled": False,
        "implemented": True,
    },
    {
        "id": "remote_companion",
        "name": "Remote / LAN Companion (2FA)",
        "description": "Opt-in authenticated remote access secured with Ed25519 / TOTP 2FA while keeping desktop localhost-only by default.",
        "category": "network",
        "privacy": "Network",
        "slash_command": "",
        "default_enabled": False,
        "implemented": False,
    },
)

_BY_ID: dict[str, dict[str, Any]] = {m["id"]: m for m in MODULE_CATALOG}

DEFAULT_MODULES: dict[str, bool] = {
    m["id"]: bool(m["default_enabled"]) for m in MODULE_CATALOG
}


def resolve_modules(settings: dict[str, Any] | None) -> dict[str, bool]:
    """Return normalized module enablement map without mutating settings."""
    resolved = dict(DEFAULT_MODULES)
    raw = (settings or {}).get("modules")
    if isinstance(raw, dict):
        for mod_id, val in raw.items():
            if mod_id in _BY_ID and isinstance(val, bool):
                resolved[mod_id] = val
    return resolved


def is_enabled(settings: dict[str, Any] | None, module_id: str) -> bool:
    """True when ``module_id`` is known and enabled in ``settings``."""
    if module_id not in _BY_ID:
        return False
    return bool(resolve_modules(settings).get(module_id, False))


def catalog_response(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Build JSON-ready catalog payload for GET/POST /api/modules."""
    state = resolve_modules(settings)
    items = []
    for entry in MODULE_CATALOG:
        row = dict(entry)
        row["enabled"] = state[entry["id"]]
        items.append(row)
    return {"ok": True, "modules": items, "flags": state}


def update_modules(
    settings_path: str,
    updates: dict[str, Any],
    lock: threading.Lock | None = None,
) -> dict[str, bool]:
    """Validate and atomically merge ``modules`` flags into ``settings.json``.

    Preserves all existing keys in ``settings.json``. Raises ``ValueError`` for
    unknown module IDs or non-boolean values.
    """
    if not isinstance(updates, dict) or not updates:
        raise ValueError("Expected a non-empty object of module flags")

    cleaned: dict[str, bool] = {}
    for mod_id, val in updates.items():
        if mod_id not in _BY_ID:
            raise ValueError(f"Unknown module: {mod_id}")
        if not isinstance(val, bool):
            raise ValueError(f"Module flag '{mod_id}' must be true or false")
        cleaned[mod_id] = val

    guard = lock or _WRITE_LOCK
    with guard:
        current: dict[str, Any] = {}
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    current = loaded
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot safely update settings.json: {exc}") from exc

        merged_modules = resolve_modules(current)
        merged_modules.update(cleaned)
        current["modules"] = merged_modules

        os.makedirs(os.path.dirname(os.path.abspath(settings_path)), exist_ok=True)
        tmp_path = settings_path + ".modules.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, settings_path)

    return merged_modules
