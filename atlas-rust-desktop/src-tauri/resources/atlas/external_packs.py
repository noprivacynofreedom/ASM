"""Opt-In External Packs Coordinator (Productivity MCP, Local Media Drawer).

Keeps IMAP/CalDAV/Media implementations cleanly isolated in their own standalone
MCP servers under src/ while giving the Atlas UI one-click MCP registration,
and safe local previews. The Remote Companion from work-2 is NOT ported (see MERGE-NOTES).

Standard library only.
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
from typing import Any

from src import mcp_media_drawer, mcp_productivity

_LOCK = threading.Lock()

MCP_PACK_DEFS = {
    "atlas-productivity": {
        "name": "atlas-productivity",
        "command": ["{python}", "-u", "{project}/src/mcp_productivity.py"],
        "cwd": "{project}",
        "enabled": True,
    },
    "atlas-media-drawer": {
        "name": "atlas-media-drawer",
        "command": ["{python}", "-u", "{project}/src/mcp_media_drawer.py"],
        "cwd": "{project}",
        "enabled": True,
    },
}


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json_atomic(path: str, payload: Any) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".pack-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def is_mcp_registered(settings: dict[str, Any], server_name: str) -> bool:
    rows = settings.get("mcp_servers") if isinstance(settings, dict) else None
    if not isinstance(rows, list):
        return False
    return any(isinstance(r, dict) and r.get("name") == server_name and r.get("enabled", True) for r in rows)


def set_mcp_registration(settings_path: str, server_name: str, registered: bool) -> list[dict[str, Any]]:
    """Atomically register or unregister a Phase 3 MCP pack in settings.json['mcp_servers']."""
    if server_name not in MCP_PACK_DEFS:
        raise ValueError(f"Unknown MCP pack: {server_name}")
    with _LOCK:
        existing = _read_json(settings_path, {})
        if not isinstance(existing, dict):
            existing = {}
        rows = [r for r in (existing.get("mcp_servers") or []) if isinstance(r, dict) and r.get("name") != server_name]
        if registered:
            rows.append(dict(MCP_PACK_DEFS[server_name]))
        existing["mcp_servers"] = rows
        _write_json_atomic(settings_path, existing)
        return rows


def _media_cfg_path(data_dir: str) -> str:
    folder = os.path.join(data_dir, ".atlas")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "media_drawer.json")


def get_media_endpoint(data_dir: str) -> str:
    cfg = _read_json(_media_cfg_path(data_dir), {})
    if isinstance(cfg, dict) and cfg.get("endpoint"):
        return str(cfg["endpoint"])
    return os.environ.get("ATLAS_MEDIA_URL") or mcp_media_drawer.DEFAULT_MEDIA_URL


def save_media_endpoint(data_dir: str, endpoint: str) -> str:
    clean = mcp_media_drawer.validate_local_endpoint(endpoint)
    _write_json_atomic(_media_cfg_path(data_dir), {"endpoint": clean, "updated_at": time.time()})
    return clean


def packs_overview(data_dir: str, settings: dict[str, Any]) -> dict[str, Any]:
    endpoint = get_media_endpoint(data_dir)
    return {
        "productivity": {
            "mcp_registered": is_mcp_registered(settings, "atlas-productivity"),
            "outbound_email_allowed": mcp_productivity.OUTBOUND_EMAIL_ALLOWED,
            "imap_configured": bool(os.environ.get("ATLAS_IMAP_HOST") and os.environ.get("ATLAS_IMAP_USER")),
            "tasks": mcp_productivity.tasks_list(data_dir=data_dir),
            "events": mcp_productivity.calendar_list(data_dir=data_dir),
        },
        "media": {
            "mcp_registered": is_mcp_registered(settings, "atlas-media-drawer"),
            "endpoint": endpoint,
            "items": mcp_media_drawer.list_media(data_dir=data_dir),
        },
    }
