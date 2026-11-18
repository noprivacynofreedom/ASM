"""Atlas Test Suite MCP server (stdio, newline-delimited JSON-RPC) & JSON store.

Persists test features, checklist tickboxes, Kanban column status
(queued | testing | passed | failed), and launch/run feedback logs in
<ATLAS_DATA_DIR>/test_suite.json (never touching data.json).

Tools: test_suite_list (read), test_suite_add (write),
       test_suite_update (write), test_suite_log_run (write).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALID_STATUSES = ("queued", "testing", "passed", "failed")
STATUS_ALIASES = {
    "queued": "queued",
    "todo": "queued",
    "testing": "testing",
    "in_progress": "testing",
    "in-progress": "testing",
    "passed": "passed",
    "pass": "passed",
    "done": "passed",
    "failed": "failed",
    "fail": "failed",
    "needs_fix": "failed",
    "needs fix": "failed",
    "needs-fix": "failed",
}
MAX_RUNS = 200
MAX_FEEDBACK_PER_FEATURE = 100
_STORE_LOCK = threading.RLock()


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def resolve_data_dir(data_dir=None):
    if data_dir is not None:
        return Path(data_dir)
    env_dir = os.environ.get("ATLAS_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return HERE / "data"


def store_path(data_dir=None):
    return resolve_data_dir(data_dir) / "test_suite.json"


def normalize_status(raw, default="queued"):
    if raw is None:
        return default
    key = str(raw).strip().lower()
    if key in STATUS_ALIASES:
        return STATUS_ALIASES[key]
    raise ValueError(f"Invalid status {raw!r}; expected one of {', '.join(VALID_STATUSES)}")


def _empty_state():
    return {"version": 1, "updated_at": _now_iso(), "features": [], "runs": []}


def _normalize_ticks(raw_ticks):
    ticks = []
    if not isinstance(raw_ticks, list):
        return ticks
    for item in raw_ticks:
        if isinstance(item, str):
            label = item.strip()
            if label:
                ticks.append({"id": _new_id("tick"), "label": label, "done": False})
        elif isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            if label:
                ticks.append({
                    "id": str(item.get("id") or _new_id("tick")),
                    "label": label,
                    "done": bool(item.get("done", False)),
                })
    return ticks


def load_suite(data_dir=None):
    path = store_path(data_dir)
    with _STORE_LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _empty_state()
        except (OSError, ValueError):
            return _empty_state()
        if not isinstance(data, dict):
            return _empty_state()
        features = data.get("features") if isinstance(data.get("features"), list) else []
        runs = data.get("runs") if isinstance(data.get("runs"), list) else []
        return {
            "version": int(data.get("version") or 1),
            "updated_at": str(data.get("updated_at") or _now_iso()),
            "features": features,
            "runs": runs,
        }


def save_suite(state, data_dir=None):
    path = store_path(data_dir)
    with _STORE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        state["version"] = 1
        state["updated_at"] = _now_iso()
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    return state


def list_suite(data_dir=None, status=None, include_runs=True, run_limit=20):
    state = load_suite(data_dir)
    features = state["features"]
    counts = {s: 0 for s in VALID_STATUSES}
    for feat in features:
        st = feat.get("status", "queued")
        if st in counts:
            counts[st] += 1
    if status is not None and str(status).strip():
        target = normalize_status(status)
        features = [f for f in features if f.get("status") == target]
    runs = []
    if include_runs:
        try:
            lim = max(1, min(MAX_RUNS, int(run_limit or 20)))
        except (TypeError, ValueError):
            lim = 20
        runs = list(reversed(state["runs"][-lim:]))
    return {
        "updated_at": state["updated_at"],
        "counts": counts,
        "features": features,
        "runs": runs,
    }


def add_feature(data_dir=None, title="", description="", status="queued", ticks=None, feedback=None, author="model"):
    clean_title = str(title or "").strip()
    if not clean_title:
        raise ValueError("title is required")
    norm_status = normalize_status(status or "queued")
    now = _now_iso()
    feat = {
        "id": _new_id("feat"),
        "title": clean_title,
        "description": str(description or "").strip(),
        "status": norm_status,
        "ticks": _normalize_ticks(ticks or []),
        "feedback": [],
        "created_at": now,
        "updated_at": now,
    }
    if feedback is not None and str(feedback).strip():
        feat["feedback"].append({
            "at": now,
            "author": str(author or "model").strip() or "model",
            "note": str(feedback).strip(),
        })
    with _STORE_LOCK:
        state = load_suite(data_dir)
        state["features"].append(feat)
        save_suite(state, data_dir)
    return feat


def update_feature(
    data_dir=None,
    feature_id="",
    status=None,
    toggle_tick=None,
    tick_id=None,
    tick_done=None,
    add_tick=None,
    feedback=None,
    author="model",
    title=None,
    description=None,
    ticks=None,
):
    fid = str(feature_id or "").strip()
    if not fid:
        raise ValueError("feature_id is required")
    with _STORE_LOCK:
        state = load_suite(data_dir)
        feat = next((f for f in state["features"] if f.get("id") == fid), None)
        if feat is None:
            raise ValueError(f"Feature not found: {fid}")
        now = _now_iso()
        if title is not None:
            clean_title = str(title).strip()
            if not clean_title:
                raise ValueError("title cannot be empty")
            feat["title"] = clean_title
        if description is not None:
            feat["description"] = str(description).strip()
        if status is not None and str(status).strip():
            feat["status"] = normalize_status(status)
        if ticks is not None:
            feat["ticks"] = _normalize_ticks(ticks)
        if add_tick is not None and str(add_tick).strip():
            feat.setdefault("ticks", []).append({
                "id": _new_id("tick"),
                "label": str(add_tick).strip(),
                "done": False,
            })
        if toggle_tick is not None and str(toggle_tick).strip():
            tid = str(toggle_tick).strip()
            tick = next((t for t in feat.get("ticks", []) if t.get("id") == tid), None)
            if tick is None:
                raise ValueError(f"Tickbox not found: {tid}")
            tick["done"] = not bool(tick.get("done"))
        if tick_id is not None and str(tick_id).strip():
            tid = str(tick_id).strip()
            tick = next((t for t in feat.get("ticks", []) if t.get("id") == tid), None)
            if tick is None:
                raise ValueError(f"Tickbox not found: {tid}")
            if tick_done is None:
                tick["done"] = not bool(tick.get("done"))
            else:
                tick["done"] = bool(tick_done)
        if feedback is not None and str(feedback).strip():
            fb_list = feat.setdefault("feedback", [])
            fb_list.append({
                "at": now,
                "author": str(author or "model").strip() or "model",
                "note": str(feedback).strip(),
            })
            if len(fb_list) > MAX_FEEDBACK_PER_FEATURE:
                del fb_list[:-MAX_FEEDBACK_PER_FEATURE]
        feat["updated_at"] = now
        save_suite(state, data_dir)
        return feat


def delete_feature(data_dir=None, feature_id=""):
    fid = str(feature_id or "").strip()
    if not fid:
        raise ValueError("feature_id is required")
    with _STORE_LOCK:
        state = load_suite(data_dir)
        before = len(state["features"])
        state["features"] = [f for f in state["features"] if f.get("id") != fid]
        if len(state["features"]) == before:
            raise ValueError(f"Feature not found: {fid}")
        save_suite(state, data_dir)
    return {"deleted": fid}


def log_run(data_dir=None, label="session", summary="", kind="test_pass", feature_feedback=None, author="model"):
    clean_label = str(label or "session").strip() or "session"
    clean_kind = str(kind or "test_pass").strip().lower() or "test_pass"
    clean_summary = str(summary or "").strip()
    if not clean_summary and clean_kind == "launch":
        clean_summary = "Atlas server started"
    now = _now_iso()
    run_id = _new_id("run")
    ff_rows = []
    if isinstance(feature_feedback, list):
        for item in feature_feedback:
            if not isinstance(item, dict):
                continue
            fid = str(item.get("feature_id") or item.get("id") or "").strip()
            if not fid:
                continue
            row = {"feature_id": fid}
            if item.get("status") is not None and str(item.get("status")).strip():
                row["status"] = normalize_status(item.get("status"))
            if item.get("note") is not None and str(item.get("note")).strip():
                row["note"] = str(item.get("note")).strip()
            ff_rows.append(row)

    run = {
        "id": run_id,
        "at": now,
        "label": clean_label,
        "kind": clean_kind,
        "summary": clean_summary,
        "feature_feedback": ff_rows,
    }
    with _STORE_LOCK:
        state = load_suite(data_dir)
        by_id = {f.get("id"): f for f in state["features"]}
        for row in ff_rows:
            feat = by_id.get(row["feature_id"])
            if feat is None:
                continue
            if "status" in row:
                feat["status"] = row["status"]
            if "note" in row:
                fb_list = feat.setdefault("feedback", [])
                fb_list.append({
                    "at": now,
                    "author": str(author or "model").strip() or "model",
                    "note": row["note"],
                    "run_id": run_id,
                })
                if len(fb_list) > MAX_FEEDBACK_PER_FEATURE:
                    del fb_list[:-MAX_FEEDBACK_PER_FEATURE]
            feat["updated_at"] = now
        state["runs"].append(run)
        if len(state["runs"]) > MAX_RUNS:
            del state["runs"][:-MAX_RUNS]
        save_suite(state, data_dir)
    return run


class TestSuiteMCP:
    def __init__(self, data_dir=None):
        self.data_dir = resolve_data_dir(data_dir)

    def test_suite_list(self, a):
        out = list_suite(
            self.data_dir,
            status=a.get("status"),
            include_runs=a.get("include_runs", True),
            run_limit=a.get("run_limit", 20),
        )
        return json.dumps(out, ensure_ascii=False, indent=2)

    def test_suite_add(self, a):
        feat = add_feature(
            self.data_dir,
            title=a.get("title", ""),
            description=a.get("description", ""),
            status=a.get("status", "queued"),
            ticks=a.get("ticks") or [],
            feedback=a.get("feedback"),
            author=a.get("author", "model"),
        )
        return json.dumps(feat, ensure_ascii=False, indent=2)

    def test_suite_update(self, a):
        feat = update_feature(
            self.data_dir,
            feature_id=a.get("feature_id") or a.get("id") or "",
            status=a.get("status"),
            toggle_tick=a.get("toggle_tick"),
            tick_id=a.get("tick_id"),
            tick_done=a.get("tick_done"),
            add_tick=a.get("add_tick"),
            feedback=a.get("feedback"),
            author=a.get("author", "model"),
            title=a.get("title"),
            description=a.get("description"),
            ticks=a.get("ticks"),
        )
        return json.dumps(feat, ensure_ascii=False, indent=2)

    def test_suite_log_run(self, a):
        run = log_run(
            self.data_dir,
            label=a.get("label", "session"),
            summary=a.get("summary", ""),
            kind=a.get("kind", "test_pass"),
            feature_feedback=a.get("feature_feedback"),
            author=a.get("author", "model"),
        )
        return json.dumps(run, ensure_ascii=False, indent=2)


def _s(props=None, required=None):
    return {"type": "object", "properties": props or {}, "required": required or []}


_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_INT = {"type": "integer"}

TOOLS = [
    (
        "test_suite_list",
        "List test suite Kanban features, tickboxes, column counts, and recent launch/run feedback logs.",
        _s({"status": _STR, "include_runs": _BOOL, "run_limit": _INT}),
    ),
    (
        "test_suite_add",
        "Add a new test feature card to the Kanban test suite with optional checklist tickboxes.",
        _s(
            {
                "title": _STR,
                "description": _STR,
                "status": _STR,
                "ticks": {"type": "array", "items": _STR},
                "feedback": _STR,
                "author": _STR,
            },
            ["title"],
        ),
    ),
    (
        "test_suite_update",
        "Update a test feature: toggle or set a tickbox, add a tickbox, move column status (queued|testing|passed|failed), or attach model feedback.",
        _s(
            {
                "feature_id": _STR,
                "status": _STR,
                "toggle_tick": _STR,
                "tick_id": _STR,
                "tick_done": _BOOL,
                "add_tick": _STR,
                "feedback": _STR,
                "author": _STR,
                "title": _STR,
                "description": _STR,
            },
            ["feature_id"],
        ),
    ),
    (
        "test_suite_log_run",
        "Record an app launch or test pass with build/session label, summary, and optional per-feature feedback/status updates.",
        _s(
            {
                "label": _STR,
                "summary": _STR,
                "kind": _STR,
                "author": _STR,
                "feature_feedback": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"feature_id": _STR, "status": _STR, "note": _STR},
                        "required": ["feature_id"],
                    },
                },
            },
            ["summary"],
        ),
    ),
]


def handle(suite, msg):
    """Return a JSON-RPC response dict, or None for notifications."""
    method, rid = msg.get("method"), msg.get("id")
    if rid is None:
        return None
    if method == "initialize":
        result = {
            "protocolVersion": (msg.get("params") or {}).get("protocolVersion") or "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "atlas-test-suite", "version": "1.0"},
        }
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        fn = getattr(suite, name, None) if name in {t[0] for t in TOOLS} else None
        if fn is None:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        try:
            out = fn(args)
            result = {"content": [{"type": "text", "text": str(out)}]}
        except Exception as exc:  # noqa: BLE001
            result = {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def main():
    suite = TestSuiteMCP()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        resp = handle(suite, msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
