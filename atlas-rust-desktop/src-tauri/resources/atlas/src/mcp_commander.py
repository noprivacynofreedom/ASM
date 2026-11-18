#!/usr/bin/env python3
"""Atlas Commander: local, read-only MCP server (JSON-RPC over stdio).

WHAT IT IS
    The only MCP server Atlas launches by default (see settings.json "mcp_servers").
    mcp_monitor.py starts it; mcp_chat.py lets the model call its tools.

WHERE IT WORKS (the "root")
    1. env ATLAS_WORKSPACE      - the folder the user chose as the working directory
    2. env ATLAS_PROJECT_ROOT   - the Atlas install/project folder
    3. the parent of this file's folder
    Every path a tool receives is resolved against the root and must stay inside it.

HOW PATHS ARE ACCEPTED
    Relative ("server.py", "src\\mcp_commander.py") or absolute paths that are inside the root.
    Windows or POSIX separators both work. Anything outside the root is rejected with a
    message that tells the model what the root is.

HOW ERRORS ARE REPORTED (MCP spec)
    A tool that fails returns a normal result with "isError": true and a text message, so the
    model can read it and recover. JSON-RPC "error" is only used for protocol problems
    (unknown method, unknown tool).

WRITES
    write_file and write_project_file (same tool, two names) create or replace ONE text file inside the root.
    They refuse existing files unless overwrite=true, refuse protected files, never delete, never run commands.
    Set env ATLAS_COMMANDER_READONLY=1 to switch both off.
WEB SEARCH
    web_search returns title, url, snippet. It needs ONE of these (search sites block scripts without an API):
      env ATLAS_BRAVE_API_KEY   - Brave Search API key (brave.com/search/api)
      env ATLAS_SEARXNG_URL     - base URL of a SearXNG server with JSON output on, e.g. http://localhost:8080
    The query text leaves this computer for Brave. Set env ATLAS_COMMANDER_OFFLINE=1 to switch it off. Git tools run fixed read-only git commands.
"""
import hashlib
import html
import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_book_spec = importlib.util.spec_from_file_location("atlas_book_commander", Path(__file__).with_name("book_commander.py"))
if _book_spec is None or _book_spec.loader is None:
    raise ImportError("Atlas Commander book tools are missing.")
book_commander = importlib.util.module_from_spec(_book_spec)
_book_spec.loader.exec_module(book_commander)

PROTOCOL = "2024-11-05"
VERSION = "0.4.0"
MAX_WRITE_BYTES = 1048576
WRITE_TOOLS = ("write_file", "write_project_file")
MAX_FILE_BYTES = 262144
MAX_LIST_ENTRIES = 200
EXCLUDED = {".git", "node_modules", "target", ".venv", "venv", "__pycache__"}
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
# Files a model must never read through this server: they hold credentials.
SECRET_NAMES = {".npmrc", ".netrc", ".pypirc", "id_rsa", "id_ed25519", "id_ecdsa", "credentials"}
SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12")


def _find_root():
    for name in ("ATLAS_WORKSPACE", "ATLAS_PROJECT_ROOT"):
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


ROOT = _find_root()


def log(message):
    """Diagnostics go to stderr; stdout is reserved for JSON-RPC."""
    sys.stderr.write(f"[atlas-commander] {message}\n")
    sys.stderr.flush()


def reply(request_id, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def safe_path(value="."):
    """Resolve a model-supplied path to a location inside ROOT, or raise ValueError."""
    raw = str(value if value not in (None, "") else ".").strip().strip("\"'").replace("\\", "/")
    candidate = Path(raw)
    candidate = (candidate if candidate.is_absolute() else ROOT / candidate).resolve()
    if candidate != ROOT and ROOT not in candidate.parents:
        raise ValueError(
            f"Path '{value}' is outside the project root ({ROOT}). "
            "Use a path relative to the root, for example \"server.py\", or call list_workspace_files."
        )
    return candidate


def rel(path):
    return str(path.relative_to(ROOT)) if path != ROOT else "."


def is_secret(path):
    """True for git internals and credential files. Listing hides .git; reading must refuse it too."""
    try:
        parts = path.relative_to(ROOT).parts
    except ValueError:
        return True
    if ".git" in parts:
        return True
    name = path.name.lower()
    return (name == ".env" or name.startswith(".env.") or name in SECRET_NAMES
            or name.endswith(SECRET_SUFFIXES))


SECRET_KEY_HINTS = ("key", "token", "secret", "password", "passwd", "credential")


def _redact(value):
    """Mask the value of any JSON field whose name looks like a credential (settings.json has upstream_api_key)."""
    if isinstance(value, dict):
        return {k: ("***redacted***" if isinstance(v, (str, int, float)) and v not in ("", None)
                    and any(h in str(k).lower() for h in SECRET_KEY_HINTS) else _redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _refuse_secret(path, requested):
    if is_secret(path):
        raise ValueError(f"'{requested}' is a protected file (git internals or credentials) and cannot be read through Atlas.")


def _schema(properties=None, required=None):
    schema = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


_PATH = {"type": "string", "description": f"Path relative to the project root {ROOT} (absolute paths inside it also work), e.g. \"server.py\"."}


def tool_definitions():
    # The model cannot see the filesystem, so every description states the root it works in.
    return _with_root_note(_tool_definitions())


def _with_root_note(tools):
    note = f" Project root: {ROOT}."
    return [{**tool, "description": tool["description"] + note} for tool in tools]


def _tool_definitions():
    # atlas_* names are kept as aliases of the *_workspace_* tools for older prompts/chats.
    return [
        {"name": "atlas_project_status", "description": "Show the project root and whether key Atlas files exist.", "inputSchema": _schema()},
        {"name": "list_workspace_files", "description": "List files and folders in a directory under the project root.", "inputSchema": _schema({"path": _PATH})},
        {"name": "read_workspace_file", "description": "Read a UTF-8 text file under the project root (max 256 KiB).", "inputSchema": _schema({"path": _PATH}, ["path"])},
        {"name": "verify_workspace_file", "description": "Check a file exists and return its size and SHA-256; optionally compare to an expected hash.",
         "inputSchema": _schema({"path": _PATH, "sha256": {"type": "string", "description": "Optional expected SHA-256."}}, ["path"])},
        {"name": "git_status", "description": "Read-only: current git branch and short status of the project root.", "inputSchema": _schema()},
        {"name": "git_diff", "description": "Read-only: git diff of the project root (truncated to 12 KB).", "inputSchema": _schema()},
        {"name": "atlas_list_files", "description": "Alias of list_workspace_files.", "inputSchema": _schema({"relative_path": _PATH, "path": _PATH})},
        *_write_tool_definitions(),
        *_swarm_tool_definitions(),
        *_web_tool_definitions(),
        *book_commander.tool_definitions(_schema, _offline()),
        {"name": "atlas_read_file", "description": "Alias of read_workspace_file.", "inputSchema": _schema({"relative_path": _PATH, "path": _PATH})},
    ]


def _offline():
    return os.environ.get("ATLAS_COMMANDER_OFFLINE", "").strip() in ("1", "true", "yes")


def _web_tool_definitions():
    if _offline():
        return []
    return [{"name": "web_search", "description": "Search the web. Returns title, url and snippet for each result. Needs ATLAS_BRAVE_API_KEY or ATLAS_SEARXNG_URL. The query leaves this computer.",
             "inputSchema": _schema({"query": {"type": "string", "description": "Search words."},
                                     "max_results": {"type": "integer", "description": "1 to 10, default 5."}}, ["query"])}]


def _get_json(url, headers=None):
    request = urllib.request.Request(url, headers={"User-Agent": "AtlasChat", "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read(1 << 20).decode("utf-8", errors="replace"))


def parse_search_results(payload, limit):
    """Accepts a Brave ({"web": {"results": [...]}}) or SearXNG ({"results": [...]}) reply."""
    items = (payload.get("web") or {}).get("results") if isinstance(payload.get("web"), dict) else payload.get("results")
    clean = lambda t: html.unescape(re.sub(r"<[^>]+>", "", str(t or ""))).strip()
    return [{"title": clean(i.get("title")), "url": i.get("url", ""), "snippet": clean(i.get("description") or i.get("content"))}
            for i in (items or [])[:limit] if isinstance(i, dict)]


def _web_search(query, limit):
    key = os.environ.get("ATLAS_BRAVE_API_KEY", "").strip()
    searx = os.environ.get("ATLAS_SEARXNG_URL", "").strip().rstrip("/")
    if key:
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({"q": query, "count": limit})
        return parse_search_results(_get_json(url, {"X-Subscription-Token": key}), limit)
    if searx:
        return parse_search_results(_get_json(searx + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"})), limit)
    raise ValueError("Web search is not set up. Set ATLAS_BRAVE_API_KEY (Brave Search API) or ATLAS_SEARXNG_URL (your SearXNG server).")


def _readonly():
    return os.environ.get("ATLAS_COMMANDER_READONLY", "").strip() in ("1", "true", "yes")


def _write_tool_definitions():
    if _readonly():
        return []
    props = {"path": _PATH, "content": {"type": "string", "description": "Full UTF-8 text of the file."},
             "overwrite": {"type": "boolean", "description": "Replace the file if it exists. Default false: an existing file is refused."}}
    text = "Write a UTF-8 text file under the project root (max 1 MiB). Creates folders. Refuses existing files unless overwrite=true."
    return [{"name": n, "description": text, "inputSchema": _schema(props, ["path", "content"])} for n in WRITE_TOOLS]


def _swarm_tool_definitions():
    tools = [
        {
            "name": "atlas_list_conversations",
            "description": "List lightweight conversation summaries (from /api/conversations or local data.json fallback) without loading full message histories.",
            "inputSchema": _schema({
                "kind": {"type": "string", "enum": ["all", "swarm", "chat"], "description": "Filter by conversation kind (default all)."},
                "archived": {"type": "string", "enum": ["all", "only", "exclude"], "description": "Filter by archive state (default all)."},
                "q": {"type": "string", "description": "Optional case-insensitive search substring."},
                "limit": {"type": "integer", "description": "Max items to return (1-1000, default 50)."},
                "offset": {"type": "integer", "description": "Pagination offset (default 0)."},
            }),
        },
        {
            "name": "atlas_swarm_runs",
            "description": "List lightweight swarm run summaries from /api/ops/swarm/runs?summary=1.",
            "inputSchema": _schema({
                "summary": {"type": "boolean", "description": "Omit verbose per-worker log lines/routes (default true)."},
                "category": {"type": "string", "description": "Optional category filter (code, research, writing, data, design, other)."},
                "state": {"type": "string", "description": "Optional state filter (queued, running, stalled, done, failed, timeout, cancelled)."},
                "limit": {"type": "integer", "description": "Max runs to return (1-200, default 40)."},
                "lines": {"type": "integer", "description": "Max log lines per worker when summary=false (0-200, default 40)."},
            }),
        },
    ]
    if not _readonly():
        tools.append({
            "name": "atlas_archive_item",
            "description": "Archive or unarchive a conversation or swarm run via the local Atlas server.",
            "inputSchema": _schema({
                "kind": {"type": "string", "enum": ["conversation", "swarm_run"], "description": "Target item type."},
                "item_id": {"type": "string", "description": "Conversation ID or swarm run_id."},
                "archived": {"type": "boolean", "description": "True to archive, false to unarchive (default true)."},
            }, ["kind", "item_id"]),
        })
    return tools


KEY_FILES = [
    "server.py", "settings.json", "mcp_monitor.py", "mcp_chat.py", "atlas_observability.py",
    "src/mcp_commander.py", "agents/atlas_agent_runtime.py",
]


def _git(args):
    if not (ROOT / ".git").exists():
        return {"available": False, "message": "The project root is not a git repository."}
    done = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=10, shell=False)
    # Keep the START of the output (the first hunks), and say when it was cut.
    return {"available": True, "exit_code": done.returncode,
            "stdout": done.stdout[:12000], "stderr": done.stderr[:4000],
            "truncated": len(done.stdout) > 12000}


_PATH_KEYS = ("path", "relative_path", "file_path", "file", "filename", "name", "directory", "dir")


def _plain(value):
    """Local models sometimes wrap an argument: {"path": {"path": "a.txt"}} or {"path": ["a.txt"]}.
    Unwrap it to the plain string instead of turning the wrapper into text ("{'path': 'a.txt'}")."""
    for _ in range(4):
        if isinstance(value, dict):
            inner = next((value[k] for k in _PATH_KEYS if value.get(k) not in (None, "")), None)
            if inner is None and len(value) == 1:
                inner = next(iter(value.values()))
            value = inner
        elif isinstance(value, (list, tuple)) and len(value) == 1:
            value = value[0]
        else:
            break
    return value


def _requested_path(arguments):
    return _plain(arguments.get("path", arguments.get("relative_path")))


def _atlas_base_url():
    """Return the validated loopback Atlas server base URL."""
    raw = os.environ.get("ATLAS_SERVER_URL", "").strip().rstrip("/")
    if raw:
        parsed = urllib.parse.urlparse(raw)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("ATLAS_SERVER_URL must be a loopback http(s) URL.")
        return raw
    port = 8090
    settings_path = ROOT / "settings.json"
    if settings_path.is_file():
        try:
            cfg = json.loads(settings_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(cfg, dict) and isinstance(cfg.get("server_port"), int) and 1 <= cfg["server_port"] <= 65535:
                port = cfg["server_port"]
        except (OSError, ValueError):
            pass
    return f"http://127.0.0.1:{port}"


def _post_json(url, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "AtlasChat", "Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read(1 << 20).decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        try:
            err = json.loads(body).get("error")
        except ValueError:
            err = body or str(exc)
        raise ValueError(f"Atlas server returned HTTP {exc.code}: {err}") from exc


def _summarize_local_chat(chat):
    """Build a lightweight conversation summary from a raw data.json chat entry."""
    cid = str(chat.get("id") or "")
    bot_id = str(chat.get("botId") or "")
    msgs = chat.get("messages") if isinstance(chat.get("messages"), list) else []
    is_swarm = bool(
        chat.get("swarmRun") or chat.get("swarm") or chat.get("swarmRole")
        or bot_id == "Swarm Lead" or re.match(r"^sw[0-9a-f]{6,}", cid)
    )
    kind = "swarm_lead" if (bot_id == "Swarm Lead" or cid.endswith("-final")) else ("swarm" if is_swarm else "chat")
    raw_title = str(chat.get("title") or "").strip()
    if not raw_title and msgs:
        first = next((m for m in msgs if isinstance(m, dict) and m.get("role") == "user"), msgs[0])
        if isinstance(first, dict):
            raw_title = str(first.get("content") or "").strip()
    title = re.sub(r"\s+", " ", raw_title)[:72] or "Untitled"
    preview = ""
    if msgs and isinstance(msgs[-1], dict):
        preview = re.sub(r"\s+", " ", str(msgs[-1].get("content") or "")).strip()[:120]
    updated = chat.get("updatedAt") or chat.get("updated_at") or chat.get("createdAt")
    run_id = chat.get("runId") or chat.get("run_id") or (cid.rsplit("-", 1)[0] if is_swarm and "-" in cid else None)
    summary = {
        "id": cid, "botId": bot_id, "title": title, "is_swarm": is_swarm, "kind": kind,
        "createdAt": chat.get("createdAt"), "updatedAt": updated, "message_count": len(msgs),
        "preview": preview, "status": chat.get("status") or ("done" if is_swarm and msgs else "idle"),
        "archived": bool(chat.get("archived", False)),
    }
    if run_id:
        summary["run_id"] = run_id
    return summary


def _atlas_list_conversations(arguments):
    kind = str(arguments.get("kind") or "all").strip().lower()
    archived = str(arguments.get("archived") or "all").strip().lower()
    query_text = str(arguments.get("q") or "").strip()
    if kind not in ("all", "swarm", "chat"):
        raise ValueError("kind must be one of: all, swarm, chat.")
    if archived not in ("all", "only", "exclude"):
        raise ValueError("archived must be one of: all, only, exclude.")
    try:
        limit = max(1, min(1000, int(arguments.get("limit") if arguments.get("limit") is not None else 50)))
        offset = max(0, int(arguments.get("offset") if arguments.get("offset") is not None else 0))
    except (TypeError, ValueError):
        raise ValueError("limit and offset must be integers.")

    params = {"kind": kind, "archived": archived, "limit": limit, "offset": offset}
    if query_text:
        params["q"] = query_text
    base_url = _atlas_base_url()
    try:
        payload = _get_json(f"{base_url}/api/conversations?{urllib.parse.urlencode(params)}")
        if isinstance(payload, dict) and isinstance(payload.get("conversations"), list):
            return {"source": "server", "total": payload.get("total", len(payload["conversations"])), "conversations": payload["conversations"]}
    except (OSError, ValueError):
        pass

    data_path = ROOT / "data.json"
    if not data_path.is_file():
        raise ValueError(f"Atlas server unreachable at {base_url} and no data.json found in {ROOT}.")
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8", errors="replace"))
    except ValueError as exc:
        raise ValueError(f"Failed to parse data.json: {exc}") from exc
    chats = raw.get("chats", []) if isinstance(raw, dict) and isinstance(raw.get("chats"), list) else []
    q_lower = query_text.lower()
    items = []
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        item = _summarize_local_chat(chat)
        if kind == "swarm" and not item["is_swarm"]:
            continue
        if kind == "chat" and item["is_swarm"]:
            continue
        if archived == "only" and not item["archived"]:
            continue
        if archived == "exclude" and item["archived"]:
            continue
        if q_lower and q_lower not in f"{item['title']} {item['preview']} {item['botId']}".lower():
            continue
        items.append(item)
    return {"source": "data.json", "total": len(items), "conversations": items[offset:offset + limit]}


def _atlas_swarm_runs(arguments):
    summary = True if arguments.get("summary") is None else bool(arguments.get("summary"))
    category = str(arguments.get("category") or "").strip().lower()
    state_filter = str(arguments.get("state") or "").strip().lower()
    try:
        limit = max(1, min(200, int(arguments.get("limit") if arguments.get("limit") is not None else 40)))
        lines = max(0, min(200, int(arguments.get("lines") if arguments.get("lines") is not None else 40)))
    except (TypeError, ValueError):
        raise ValueError("limit and lines must be integers.")

    params = {"summary": "1" if summary else "0", "limit": limit, "lines": lines}
    if category:
        params["category"] = category
    if state_filter:
        params["state"] = state_filter
    base_url = _atlas_base_url()
    try:
        return _get_json(f"{base_url}/api/ops/swarm/runs?{urllib.parse.urlencode(params)}")
    except (OSError, ValueError) as exc:
        raise ValueError(f"Failed to fetch swarm runs from {base_url}: {exc}") from exc


def _atlas_archive_item(arguments):
    if _readonly():
        raise ValueError("Writing is switched off (ATLAS_COMMANDER_READONLY).")
    kind = str(arguments.get("kind") or "").strip().lower()
    item_id = str(arguments.get("item_id") or "").strip()
    archived = True if arguments.get("archived") is None else bool(arguments.get("archived"))
    if kind not in ("conversation", "swarm_run"):
        raise ValueError("kind must be 'conversation' or 'swarm_run'.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", item_id):
        raise ValueError("Invalid item_id: expected 1-128 alphanumeric, '_' or '-' characters.")
    base_url = _atlas_base_url()
    path = f"/api/conversations/{item_id}/archive" if kind == "conversation" else f"/api/ops/swarm/runs/{item_id}/archive"
    try:
        return _post_json(base_url + path, {"archived": archived})
    except OSError as exc:
        raise ValueError(f"Atlas server unreachable at {base_url}: {exc}") from exc


def call_tool(name, arguments):
    """Return a JSON-serialisable dict. Raise ValueError for bad input (reported as isError)."""
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object.")

    if name.startswith("book_"):
        return book_commander.call_tool(name, arguments, ROOT)

    if name == "atlas_project_status":
        return {"project_root": str(ROOT), "files": {item: (ROOT / item).is_file() for item in KEY_FILES}}

    if name in ("list_workspace_files", "atlas_list_files"):
        requested = _requested_path(arguments) or "."
        directory = safe_path(requested)
        if not directory.is_dir():
            raise ValueError(f"Folder not found: {requested}. Root is {ROOT}; call list_workspace_files with no path to see it.")
        entries, truncated = [], False
        for item in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.name in EXCLUDED or is_secret(item):
                continue
            if len(entries) >= MAX_LIST_ENTRIES:
                truncated = True
                break
            entries.append({"name": item.name, "type": "directory" if item.is_dir() else "file"})
        return {"path": rel(directory), "entries": entries, "truncated": truncated}

    if name in ("read_workspace_file", "atlas_read_file"):
        requested = _requested_path(arguments)
        if not requested:
            raise ValueError('No file path given. Pass {"path": "server.py"} or call list_workspace_files first.')
        path = safe_path(requested)
        _refuse_secret(path, requested)
        if not path.is_file():
            raise ValueError(f"File not found: {requested}. Root is {ROOT}; call list_workspace_files to see what exists.")
        size = path.stat().st_size  # check before reading: a huge file must not be loaded into memory
        if size > MAX_FILE_BYTES:
            raise ValueError(f"File is {size} bytes; the read limit is {MAX_FILE_BYTES}.")
        data = path.read_bytes()
        if b"\x00" in data[:4096]:
            raise ValueError(f"'{requested}' looks like a binary file; only text files can be read. Use verify_workspace_file for its size and hash.")
        text = data.decode("utf-8-sig", errors="replace")
        if path.suffix.lower() == ".json" and path.name.lower() in ("settings.json", "config.json"):
            try:
                text = json.dumps(_redact(json.loads(text)), indent=2, ensure_ascii=False)
            except ValueError:
                pass  # not valid JSON: return as-is
        return {"path": rel(path), "content": text}

    if name == "verify_workspace_file":
        requested = _requested_path(arguments)
        if not requested:
            raise ValueError('No file path given. Pass {"path": "server.py"}.')
        path = safe_path(requested)
        _refuse_secret(path, requested)
        if not path.is_file():
            return {"path": rel(path), "verified": False, "check": "file_exists"}
        hasher, size = hashlib.sha256(), 0
        with path.open("rb") as handle:  # stream: verifying a big file must not load it whole
            for block in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(block)
                size += len(block)
        digest = hasher.hexdigest()
        expected = str(arguments.get("sha256") or "").strip().lower()
        return {"path": rel(path), "size_bytes": size, "sha256": digest,
                "check": "file_exists_and_sha256" if expected else "file_exists",
                "expected_sha256": expected or None, "verified": (not expected) or expected == digest}

    if name in WRITE_TOOLS:
        if _readonly():
            raise ValueError("Writing is switched off (ATLAS_COMMANDER_READONLY).")
        requested = _requested_path(arguments)
        content = arguments.get("content")
        if not requested:
            raise ValueError('No file path given. Pass {"path": "notes.txt", "content": "..."}.')
        if not isinstance(content, str):
            raise ValueError("'content' must be a string.")
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise ValueError(f"Content is {len(data)} bytes; the write limit is {MAX_WRITE_BYTES}.")
        path = safe_path(requested)
        if path == ROOT:
            raise ValueError("Give a file path, not the project root.")
        if is_secret(path) or EXCLUDED.intersection(path.relative_to(ROOT).parts):
            raise ValueError(f"'{requested}' is protected (git, credentials or build folders) and cannot be written.")
        existed = path.exists()
        if path.is_dir():
            raise ValueError(f"'{requested}' is a folder.")
        if existed and arguments.get("overwrite") is not True:
            raise ValueError(f"'{requested}' already exists. Pass overwrite=true to replace it.")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".atlas-tmp")
        temp.write_bytes(data)
        os.replace(temp, path)  # atomic: a crash never leaves a half-written file
        return {"path": rel(path), "bytes_written": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "created": not existed, "overwritten": existed}

    if name == "web_search":
        if _offline():
            raise ValueError("Web search is switched off (ATLAS_COMMANDER_OFFLINE).")
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError('No query given. Pass {"query": "search words"}.')
        try:
            limit = max(1, min(10, int(arguments.get("max_results") or 5)))
        except (TypeError, ValueError):
            raise ValueError("max_results must be a number from 1 to 10.")
        try:
            results = _web_search(query, limit)
        except (OSError, ValueError) as exc:
            raise ValueError(str(exc) if isinstance(exc, ValueError) else f"Web search failed: {exc}")
        return {"query": query, "results": results}

    if name == "git_status":
        out = _git(["status", "--short", "--branch"])
        if out.get("available"):
            out["branch"] = _git(["branch", "--show-current"]).get("stdout", "").strip()
        return out

    if name == "git_diff":
        return _git(["diff", "--no-ext-diff", "--", "."])

    if name == "atlas_list_conversations":
        return _atlas_list_conversations(arguments)

    if name == "atlas_swarm_runs":
        return _atlas_swarm_runs(arguments)

    if name == "atlas_archive_item":
        return _atlas_archive_item(arguments)

    raise LookupError("Unknown Atlas tool: " + str(name))


def tool_result(result, is_error=False):
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    out = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if not is_error and isinstance(result, dict):
        out["structuredContent"] = result
    return out


def handle(message):
    request_id = message.get("id")
    method = message.get("method")

    if not isinstance(method, str):
        if request_id is not None:
            reply(request_id, error={"code": -32600, "message": "Invalid Request: 'method' must be a string"})
        return
    if request_id is None:
        return  # JSON-RPC notification: never answer it (notifications/* and any other id-less message)
    if method == "initialize":
        params = message.get("params")
        asked = params.get("protocolVersion") if isinstance(params, dict) else None
        reply(request_id, {"protocolVersion": asked if asked in SUPPORTED_PROTOCOLS else PROTOCOL,
                           "capabilities": {"tools": {"listChanged": False}},
                           "serverInfo": {"name": "atlas-commander", "version": VERSION}})
    elif method == "ping":
        reply(request_id, {})
    elif method == "tools/list":
        reply(request_id, {"tools": tool_definitions()})
    elif method == "tools/call":
        params = message.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            reply(request_id, error={"code": -32602, "message": "Invalid params: expected an object with 'name' and 'arguments'"})
            return
        try:
            reply(request_id, tool_result(call_tool(params.get("name"), params.get("arguments") or {})))
        except LookupError as exc:
            reply(request_id, error={"code": -32602, "message": str(exc)})
        except Exception as exc:  # tool failures are results, not protocol errors
            reply(request_id, tool_result(f"{type(exc).__name__}: {exc}", is_error=True))
    else:
        reply(request_id, error={"code": -32601, "message": "Method not found: " + str(method)})


def _use_utf8_stdio():
    """JSON-RPC is UTF-8. On Windows the default console code page (cp1252) garbles or rejects
    non-ASCII file content, so force UTF-8 on the stdio streams."""
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main():
    _use_utf8_stdio()
    log(f"root = {ROOT}")
    for line in sys.stdin:
        if not line.strip():
            continue
        request_id = None
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("Expected a JSON-RPC object.")
            request_id = message.get("id")
            handle(message)
        except Exception as exc:
            log(f"request failed: {type(exc).__name__}: {exc}")
            if request_id is not None:
                reply(request_id, error={"code": -32603, "message": str(exc)})


if __name__ == "__main__":
    main()
