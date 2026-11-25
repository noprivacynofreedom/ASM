"""Atlas Productivity MCP Pack (Phase 3 — Opt-In External MCP Server).

Standalone JSON-RPC 2.0 stdio MCP server kept outside core server.py.
Provides:
  - Local Tasks (tasks_list, tasks_add, tasks_toggle) stored in <DATA_DIR>/.atlas/tasks.json
  - Local Calendar (calendar_list, calendar_add) stored in <DATA_DIR>/.atlas/calendar.json
  - Read-only IMAP inbox triage (email_triage_readonly) using environment variables only

HARD SAFETY RULE (CLAUDE.md §6):
  Outbound email sending is permanently disabled. No SMTP client or email_send
  tool exists in this server.

Standard library only.
"""
from __future__ import annotations

import email.header
import imaplib
import json
import os
import secrets
import sys
import tempfile
import time
from typing import Any

OUTBOUND_EMAIL_ALLOWED = False  # Hard-disabled per CLAUDE.md §6

SERVER_INFO = {"name": "atlas-productivity", "version": "0.1.0"}

TOOLS = [
    {
        "name": "tasks_list",
        "description": "List local Atlas tasks (optional status filter: open, done, all).",
        "inputSchema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["all", "open", "done"]}},
        },
    },
    {
        "name": "tasks_add",
        "description": "Add a local task with optional due date and priority.",
        "inputSchema": {
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {"type": "string"},
                "due": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "normal", "high"]},
            },
        },
    },
    {
        "name": "tasks_toggle",
        "description": "Mark a local task done or open by id.",
        "inputSchema": {
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "string"}, "done": {"type": "boolean"}},
        },
    },
    {
        "name": "calendar_list",
        "description": "List upcoming local calendar events.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "calendar_add",
        "description": "Add a local calendar event (ISO date/time string).",
        "inputSchema": {
            "type": "object",
            "required": ["title", "start"],
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string"},
                "notes": {"type": "string"},
            },
        },
    },
    {
        "name": "email_triage_readonly",
        "description": "Read-only IMAP inbox header summary (requires ATLAS_IMAP_HOST, ATLAS_IMAP_USER, ATLAS_IMAP_PASS env vars). Sending email is permanently disabled.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
]


def _data_dir() -> str:
    base = os.environ.get("ATLAS_DATA_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    folder = os.path.join(base, ".atlas")
    os.makedirs(folder, exist_ok=True)
    return folder


def _read_json_list(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_json_atomic(path: str, payload: Any) -> None:
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".prod-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def tasks_list(data_dir: str | None = None, status: str = "all") -> list[dict[str, Any]]:
    folder = os.path.join(data_dir, ".atlas") if data_dir else _data_dir()
    rows = _read_json_list(os.path.join(folder, "tasks.json"))
    st = str(status or "all").lower()
    if st == "open":
        return [r for r in rows if not r.get("done")]
    if st == "done":
        return [r for r in rows if r.get("done")]
    return rows


def tasks_add(title: str, *, due: str = "", priority: str = "normal", data_dir: str | None = None) -> dict[str, Any]:
    clean = str(title or "").strip()[:300]
    if not clean:
        raise ValueError("Task title is required")
    prio = str(priority or "normal").lower()
    if prio not in ("low", "normal", "high"):
        prio = "normal"
    folder = os.path.join(data_dir, ".atlas") if data_dir else _data_dir()
    path = os.path.join(folder, "tasks.json")
    rows = _read_json_list(path)
    item = {
        "id": "tsk-" + secrets.token_hex(4),
        "title": clean,
        "due": str(due or "").strip()[:40],
        "priority": prio,
        "done": False,
        "created_at": time.time(),
    }
    rows.insert(0, item)
    _write_json_atomic(path, rows[:500])
    return item


def tasks_toggle(task_id: str, done: bool | None = None, *, data_dir: str | None = None) -> dict[str, Any]:
    folder = os.path.join(data_dir, ".atlas") if data_dir else _data_dir()
    path = os.path.join(folder, "tasks.json")
    rows = _read_json_list(path)
    hit = next((r for r in rows if r.get("id") == str(task_id or "").strip()), None)
    if not hit:
        raise KeyError("Task not found")
    hit["done"] = (not bool(hit.get("done"))) if done is None else bool(done)
    _write_json_atomic(path, rows)
    return hit


def calendar_list(data_dir: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    folder = os.path.join(data_dir, ".atlas") if data_dir else _data_dir()
    rows = _read_json_list(os.path.join(folder, "calendar.json"))
    rows.sort(key=lambda r: str(r.get("start") or ""))
    return rows[: max(1, min(200, int(limit or 50)))]


def calendar_add(title: str, start: str, *, notes: str = "", data_dir: str | None = None) -> dict[str, Any]:
    clean_title = str(title or "").strip()[:200]
    clean_start = str(start or "").strip()[:40]
    if not clean_title or not clean_start:
        raise ValueError("Calendar event title and start date/time are required")
    folder = os.path.join(data_dir, ".atlas") if data_dir else _data_dir()
    path = os.path.join(folder, "calendar.json")
    rows = _read_json_list(path)
    item = {
        "id": "cal-" + secrets.token_hex(4),
        "title": clean_title,
        "start": clean_start,
        "notes": str(notes or "").strip()[:1000],
        "created_at": time.time(),
    }
    rows.append(item)
    rows.sort(key=lambda r: str(r.get("start") or ""))
    _write_json_atomic(path, rows[:500])
    return item


def _decode_header_val(raw: str) -> str:
    parts = email.header.decode_header(raw or "")
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(str(text))
    return "".join(out)


def email_triage_readonly(limit: int = 10) -> dict[str, Any]:
    """Read-only IMAP header triage. Never sends or modifies mail."""
    host = os.environ.get("ATLAS_IMAP_HOST", "").strip()
    user = os.environ.get("ATLAS_IMAP_USER", "").strip()
    pw = os.environ.get("ATLAS_IMAP_PASS", "").strip()
    if not (host and user and pw):
        return {
            "configured": False,
            "outbound_email_allowed": OUTBOUND_EMAIL_ALLOWED,
            "messages": [],
            "note": "Read-only IMAP not configured. Set ATLAS_IMAP_HOST, ATLAS_IMAP_USER, and ATLAS_IMAP_PASS env vars. Outbound email sending is permanently disabled.",
        }
    port = int(os.environ.get("ATLAS_IMAP_PORT", "993") or 993)
    cap = max(1, min(30, int(limit or 10)))
    messages = []
    conn = imaplib.IMAP4_SSL(host, port)
    try:
        conn.login(user, pw)
        conn.select("INBOX", readonly=True)
        _typ, data = conn.search(None, "ALL")
        ids = (data[0] or b"").split()[-cap:]
        for mid in reversed(ids):
            _t, msg_data = conn.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            raw_hdr = msg_data[0][1].decode("utf-8", errors="replace") if msg_data and isinstance(msg_data[0], tuple) else ""
            parsed = email.message_from_string(raw_hdr)
            messages.append({
                "from": _decode_header_val(parsed.get("From", "")),
                "subject": _decode_header_val(parsed.get("Subject", "(no subject)")),
                "date": parsed.get("Date", ""),
            })
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return {"configured": True, "outbound_email_allowed": OUTBOUND_EMAIL_ALLOWED, "messages": messages}


def call_tool(name: str, args: dict[str, Any] | None = None, *, data_dir: str | None = None) -> dict[str, Any]:
    a = args if isinstance(args, dict) else {}
    if name == "tasks_list":
        return {"ok": True, "tasks": tasks_list(data_dir=data_dir, status=str(a.get("status") or "all"))}
    if name == "tasks_add":
        return {"ok": True, "task": tasks_add(a.get("title", ""), due=a.get("due", ""), priority=a.get("priority", "normal"), data_dir=data_dir)}
    if name == "tasks_toggle":
        return {"ok": True, "task": tasks_toggle(a.get("id", ""), a.get("done"), data_dir=data_dir)}
    if name == "calendar_list":
        return {"ok": True, "events": calendar_list(data_dir=data_dir, limit=int(a.get("limit") or 50))}
    if name == "calendar_add":
        return {"ok": True, "event": calendar_add(a.get("title", ""), a.get("start", ""), notes=a.get("notes", ""), data_dir=data_dir)}
    if name == "email_triage_readonly":
        return {"ok": True, **email_triage_readonly(limit=int(a.get("limit") or 10))}
    raise ValueError(f"Unknown productivity tool: {name}")


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
                res = {"error": {"code": -32601, "message": f"Unsupported method: {method}"}}
                if rid is not None:
                    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, **res}) + "\n")
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
