"""Atlas Swarm Workspace MCP server (stdio, newline-delimited JSON-RPC). Standard library only.

Lets an agent discover swarm runs and read the files they saved
(<workspace or data folder>/swarm-output/<run_id>/: answers as .md, code under code/).
It calls this PC's Atlas server over loopback (ATLAS_SERVER_URL, else the port in settings.json).

Tools (all read-only): swarm_runs, swarm_files, swarm_read_file.
Tiers live in mcp_chat.TOOL_TIERS (all read).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN_RE = re.compile(r"sw[0-9a-f]{4,32}")
MAX_TEXT = 20000


def log(msg):
    sys.stderr.write(f"[swarm_workspace_mcp] {msg}\n")
    sys.stderr.flush()


def base_url():
    """Validated loopback Atlas server base URL (same rule as Atlas Commander)."""
    raw = os.environ.get("ATLAS_SERVER_URL", "").strip().rstrip("/")
    if raw:
        p = urllib.parse.urlparse(raw)
        if p.scheme not in ("http", "https") or p.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("ATLAS_SERVER_URL must be a loopback http(s) URL.")
        return raw
    port = 8090
    cfg = HERE / "settings.json"
    data = os.environ.get("ATLAS_DATA_DIR", "").strip()
    if data:
        cfg = Path(data) / "settings.json"
    if cfg.is_file():
        try:
            loaded = json.loads(cfg.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("server_port"), int) and 1 <= loaded["server_port"] <= 65535:
                port = loaded["server_port"]
        except (OSError, ValueError):
            pass
    return f"http://127.0.0.1:{port}"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-swarm-workspace", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read()).get("error") or ""
        except (ValueError, AttributeError):
            msg = ""
        raise RuntimeError(f"Atlas server HTTP {exc.code}: {msg or exc.reason}") from None
    except OSError as exc:
        raise RuntimeError(f"Atlas server not reachable: {exc}") from None


def _run_id(a):
    run = str(a.get("run_id") or "").strip()
    if not RUN_RE.fullmatch(run):
        raise ValueError("Invalid run_id: expected 'sw' and hex digits, e.g. sw12ab34cd; get it from swarm_runs.")
    return run


def swarm_runs(a):
    try:
        limit = max(1, min(200, int(a.get("limit") or 40)))
    except (TypeError, ValueError):
        limit = 40
    data = get_json(base_url() + "/api/ops/swarm/runs?" + urllib.parse.urlencode({"summary": "1", "limit": limit}))
    runs = data.get("runs") if isinstance(data, dict) else None
    if not runs:
        return "No swarm runs yet."
    rows = []
    for r in runs:
        rows.append(f"{r.get('run_id', '?')} [{r.get('status', '?')}] {str(r.get('title') or r.get('goal') or '').strip()[:80]}")
    return "\n".join(rows)


def swarm_files(a):
    run = _run_id(a)
    data = get_json(f"{base_url()}/api/ops/swarm/runs/{run}/files")
    files = data.get("files") or []
    if not files:
        return f"{run}: no saved files (the run may still be working, or saved nothing)."
    return "\n".join(f"{f['path']} ({f.get('size', 0)} bytes)" for f in files)


def swarm_read_file(a):
    run = _run_id(a)
    path = str(a.get("path") or "").strip()
    if not path:
        raise ValueError('No file path given. Pass {"run_id": "...", "path": "code/app.py"}; see swarm_files.')
    data = get_json(f"{base_url()}/api/ops/swarm/runs/{run}/files?" + urllib.parse.urlencode({"path": path}))
    text = data.get("text")
    if not isinstance(text, str):
        return f"{path}: not a text file (images and binaries are not returned)."
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "\n...[truncated]"


def _s(props=None, required=None):
    return {"type": "object", "properties": props or {}, "required": required or []}


_STR, _INT = {"type": "string"}, {"type": "integer"}
_RUN = {"run_id": {"type": "string", "description": "Swarm run id, e.g. sw12ab34cd (from swarm_runs)."}}
TOOLS = [
    ("swarm_runs", "List recent swarm runs (id, status, goal). Start here to get a run_id.", _s({"limit": _INT})),
    ("swarm_files", "List the files a swarm run saved (answers as .md, code under code/).", _s(_RUN, ["run_id"])),
    ("swarm_read_file", "Read one file a swarm run saved. path comes from swarm_files, e.g. \"code/app.py\".",
     _s({**_RUN, "path": _STR}, ["run_id", "path"])),
]
_FN = {name: globals()[name] for name, _, _ in TOOLS}


def handle(msg):
    method, rid = msg.get("method"), msg.get("id")
    if rid is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion") or "2024-11-05",
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "atlas-swarm-workspace", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        fn = _FN.get(params.get("name"))
        if fn is None:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool {params.get('name')}"}}
        try:
            result = {"content": [{"type": "text", "text": str(fn(params.get("arguments") or {}))}]}
        except Exception as exc:  # noqa: BLE001
            result = {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict):
            resp = handle(msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, separators=(",", ":")) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
