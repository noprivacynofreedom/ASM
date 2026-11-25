"""Atlas Local Media Drawer MCP Pack (Phase 3 — Opt-In External MCP Server).

Standalone JSON-RPC 2.0 stdio MCP server bridging a local image generation
endpoint (Automatic1111 / Forge / ComfyUI / OpenAI-compatible local image API)
outside core server.py, storing generated images locally in <DATA_DIR>/.atlas/media/.

Standard library only.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)
from typing import Any

SERVER_INFO = {"name": "atlas-media-drawer", "version": "0.1.0"}
DEFAULT_MEDIA_URL = "http://127.0.0.1:7860"

TOOLS = [
    {
        "name": "media_status",
        "description": "Check whether the configured local image generation server is reachable.",
        "inputSchema": {"type": "object", "properties": {"endpoint": {"type": "string"}}},
    },
    {
        "name": "media_list",
        "description": "List locally generated media assets saved in Atlas.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "media_generate",
        "description": "Generate an image using a local Automatic1111 or OpenAI-compatible image server.",
        "inputSchema": {
            "type": "object",
            "required": ["prompt"],
            "properties": {
                "prompt": {"type": "string"},
                "negative_prompt": {"type": "string"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "endpoint": {"type": "string"},
            },
        },
    },
]


def _media_dir(data_dir: str | None = None) -> str:
    base = data_dir or os.environ.get("ATLAS_DATA_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    folder = os.path.join(base, ".atlas", "media")
    os.makedirs(folder, exist_ok=True)
    return folder


def validate_local_endpoint(url: str) -> str:
    clean = str(url or DEFAULT_MEDIA_URL).strip().rstrip("/")
    parsed = urlparse(clean)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Media endpoint must be a valid http:// or https:// URL")
    if parsed.hostname.lower() not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Media endpoint must be on this PC (127.0.0.1 or localhost)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Media endpoint must be a plain host and port")
    return clean


def probe_endpoint(endpoint: str = "") -> dict[str, Any]:
    url = validate_local_endpoint(endpoint or os.environ.get("ATLAS_MEDIA_URL") or DEFAULT_MEDIA_URL)
    for suffix, backend in (("/sdapi/v1/sd-models", "automatic1111"), ("/system_stats", "comfyui"), ("/v1/models", "openai-image")):
        try:
            req = urllib.request.Request(url + suffix, method="GET")
            with _OPENER.open(req, timeout=2.5) as resp:
                if 200 <= resp.status < 300:
                    return {"reachable": True, "endpoint": url, "backend": backend, "status": resp.status}
        except Exception:
            continue
    return {
        "reachable": False,
        "endpoint": url,
        "backend": "none",
        "note": "No local image backend responded. Start Automatic1111 (--api on :7860), ComfyUI (:8188), or an OpenAI-compatible local image server.",
    }


def list_media(data_dir: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    folder = _media_dir(data_dir)
    items = []
    for fname in os.listdir(folder):
        if not fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        full = os.path.join(folder, fname)
        try:
            st = os.stat(full)
        except OSError:
            continue
        meta_path = os.path.splitext(full)[0] + ".json"
        meta = {}
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            pass
        items.append({
            "file": fname,
            "bytes": st.st_size,
            "created_at": meta.get("created_at") or st.st_mtime,
            "prompt": meta.get("prompt", ""),
            "backend": meta.get("backend", "local"),
        })
    items.sort(key=lambda r: -float(r["created_at"]))
    return items[: max(1, min(100, int(limit or 30)))]


def generate_media(
    prompt: str,
    *,
    negative_prompt: str = "",
    width: int = 768,
    height: int = 768,
    endpoint: str = "",
    data_dir: str | None = None,
) -> dict[str, Any]:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ValueError("Image prompt is required")
    status = probe_endpoint(endpoint)
    if not status["reachable"]:
        raise RuntimeError(status["note"])

    url = status["endpoint"]
    w = max(256, min(1536, int(width or 768)))
    h = max(256, min(1536, int(height or 768)))
    raw_bytes = b""

    if status["backend"] == "automatic1111":
        payload = {"prompt": clean_prompt, "negative_prompt": str(negative_prompt or ""), "width": w, "height": h, "steps": 20}
        req = urllib.request.Request(url + "/sdapi/v1/txt2img", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with _OPENER.open(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        b64 = (data.get("images") or [""])[0].split(",")[-1]
        raw_bytes = base64.b64decode(b64)
    elif status["backend"] == "openai-image":
        payload = {"prompt": clean_prompt, "size": f"{w}x{h}", "response_format": "b64_json"}
        req = urllib.request.Request(url + "/v1/images/generations", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with _OPENER.open(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        b64 = ((data.get("data") or [{}])[0]).get("b64_json") or ""
        raw_bytes = base64.b64decode(b64)
    else:
        raise RuntimeError("ComfyUI detected; supply a workflow graph via ComfyUI API or use an Automatic1111 / OpenAI-compatible image endpoint.")

    if not raw_bytes:
        raise RuntimeError("Local image backend returned empty image data")

    folder = _media_dir(data_dir)
    stem = f"atlas-img-{int(time.time())}-{secrets.token_hex(3)}"
    img_path = os.path.join(folder, stem + ".png")
    with open(img_path, "wb") as f:
        f.write(raw_bytes)
    meta = {"file": stem + ".png", "prompt": clean_prompt, "width": w, "height": h, "backend": status["backend"], "created_at": time.time()}
    with open(os.path.join(folder, stem + ".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta


def call_tool(name: str, args: dict[str, Any] | None = None, *, data_dir: str | None = None) -> dict[str, Any]:
    a = args if isinstance(args, dict) else {}
    if name == "media_status":
        return {"ok": True, **probe_endpoint(str(a.get("endpoint") or ""))}
    if name == "media_list":
        return {"ok": True, "items": list_media(data_dir=data_dir, limit=int(a.get("limit") or 30))}
    if name == "media_generate":
        return {
            "ok": True,
            "item": generate_media(
                a.get("prompt", ""),
                negative_prompt=a.get("negative_prompt", ""),
                width=int(a.get("width") or 768),
                height=int(a.get("height") or 768),
                endpoint=str(a.get("endpoint") or ""),
                data_dir=data_dir,
            ),
        }
    raise ValueError(f"Unknown media tool: {name}")


def _serve_stdio() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        rid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        if method == "notifications/initialized":
            continue
        try:
            if method == "initialize":
                res = {"protocolVersion": "2024-11-05", "serverInfo": SERVER_INFO, "capabilities": {"tools": {}}}
            elif method == "tools/list":
                res = {"tools": TOOLS}
            elif method == "tools/call":
                out = call_tool(str(params.get("name") or ""), params.get("arguments") or {})
                res = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}
            else:
                if rid is not None:
                    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unsupported method: {method}"}}) + "\n")
                    sys.stdout.flush()
                continue
            if rid is not None:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": res}, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            if rid is not None:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": str(exc)}}) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    _serve_stdio()
