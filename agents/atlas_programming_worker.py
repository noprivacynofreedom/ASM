#!/usr/bin/env python3
"""Atlas Swarm Programming Worker.

Consumes `programming` tasks from the Atlas Swarm API and writes generated
project files beneath a locally configured workspace root. It never executes
commands received from the server.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import tempfile
import time
from pathlib import Path
from typing import Any

MAX_FILES = 250
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MARKER = ".atlas-swarm-task.json"


def _safe_component(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-_")
    if not value or value in {".", ".."}:
        raise ValueError("project_name must contain letters or numbers")
    return value[:80]


def _safe_relative_path(value: str) -> Path:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError(f"File path must be relative: {value!r}")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"Unsafe relative file path: {value!r}")
    if any(":" in part for part in parts):
        raise ValueError(f"Invalid file path component: {value!r}")
    return Path(*parts)


def _normalise_files(value: Any) -> list[tuple[Path, bytes]]:
    if isinstance(value, dict):
        entries = [{"path": k, "content": v} for k, v in value.items()]
    elif isinstance(value, list):
        entries = value
    else:
        raise ValueError("payload.files must be an object or a list of {path, content}")

    if not entries or len(entries) > MAX_FILES:
        raise ValueError(f"Provide between 1 and {MAX_FILES} files")

    result: list[tuple[Path, bytes]] = []
    seen: set[str] = set()
    total = 0
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("content"), str):
            raise ValueError("Each file requires string fields: path and content")
        rel = _safe_relative_path(item.get("path"))
        key = rel.as_posix().casefold()
        if key == MARKER.casefold() or key in seen:
            raise ValueError(f"Duplicate or reserved file path: {rel.as_posix()}")
        seen.add(key)
        data = item["content"].encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"{rel.as_posix()} exceeds the 2 MiB per-file limit")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Task exceeds the 20 MiB total output limit")
        result.append((rel, data))
    return result


def _atomic_write(destination: Path, data: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Refuse symlinks anywhere in the destination chain.
    current = destination.parent
    while current != current.parent:
        if current.is_symlink():
            raise ValueError(f"Refusing to write through symlink: {current}")
        current = current.parent
    if destination.exists() and destination.is_symlink():
        raise ValueError(f"Refusing to overwrite symlink: {destination}")
    fd, temp_name = tempfile.mkstemp(prefix=".atlas-write-", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, destination)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def execute_programming_task(task: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    if not isinstance(task, dict):
        raise ValueError("Swarm task must be an object")
    task_type = str(task.get("task_type") or task.get("type") or "")
    if task_type != "programming":
        raise ValueError(f"Unsupported task type: {task_type!r}; this worker accepts 'programming'")

    payload = task.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Programming task payload must be an object")

    task_id = str(task.get("task_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
        raise ValueError("Task is missing a valid task_id")

    project_name = _safe_component(payload.get("project_name") or "atlas-programming-task")
    task_folder = f"{project_name}-{task_id[-12:]}"
    root = workspace_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("Workspace root cannot be a symlink")

    target = (root / task_folder).resolve()
    if target.parent != root:
        raise ValueError("Resolved task folder escaped the configured workspace root")

    marker = target / MARKER
    if target.exists():
        if not marker.is_file():
            raise FileExistsError(f"Refusing to reuse existing folder without Atlas task marker: {target}")
        existing = json.loads(marker.read_text(encoding="utf-8"))
        if existing.get("task_id") != task_id:
            raise FileExistsError(f"Task folder belongs to a different task: {target}")
    else:
        target.mkdir(parents=False, exist_ok=False)

    files = _normalise_files(payload.get("files"))
    written = []
    digest = hashlib.sha256()
    for relative, data in files:
        destination = target / relative
        resolved_parent = destination.parent.resolve()
        if resolved_parent != target and target not in resolved_parent.parents:
            raise ValueError(f"File path escaped task folder: {relative}")
        _atomic_write(destination, data)
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        written.append({"path": relative.as_posix(), "bytes": len(data)})

    manifest = {
        "task_id": task_id,
        "project_name": project_name,
        "created_by": "atlas-swarm-programming-worker",
        "files": written,
        "sha256": digest.hexdigest(),
        "updated_at": time.time(),
    }
    _atomic_write(marker, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    return {
        "ok": True,
        "task_id": task_id,
        "workspace": str(target),
        "files_written": len(written),
        "total_bytes": sum(item["bytes"] for item in written),
        "sha256": manifest["sha256"],
        "executed_commands": 0,
    }


def self_test() -> int:
    import shutil
    import uuid

    root = Path(tempfile.gettempdir()) / f"atlas-swarm-worker-test-{uuid.uuid4().hex[:8]}"
    try:
        result = execute_programming_task(
            {
                "task_id": "tsk_selftest_000000000001",
                "task_type": "programming",
                "payload": {
                    "project_name": "first-run-check",
                    "files": [
                        {"path": "src/hello.py", "content": 'print("Atlas Swarm OK")\n'},
                        {"path": "README.md", "content": "# Atlas Swarm worker self-test\n"},
                    ],
                },
            },
            root,
        )
        expected = root / "first-run-check-000000000001" / "src" / "hello.py"
        assert expected.is_file()
        assert expected.read_text(encoding="utf-8") == 'print("Atlas Swarm OK")\n'
        print(json.dumps(result, indent=2))
        print("SELF-TEST PASSED")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Atlas Swarm programming worker")
    parser.add_argument("--server", default="http://127.0.0.1:8090", help="Atlas API base URL")
    parser.add_argument("--workspace-root", default="", help="Parent directory for generated project folders")
    parser.add_argument("--name", default="atlas-programming-worker")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    # In a frozen PyInstaller build __file__ points into the temporary extraction
    # directory. Anchor the default workspace beside the executable instead.
    runtime_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    workspace = Path(args.workspace_root).expanduser() if args.workspace_root else runtime_root / "swarm-workspaces"
    workspace.mkdir(parents=True, exist_ok=True)
    workspace = workspace.resolve()

    def execute(task: dict[str, Any]) -> dict[str, Any]:
        return execute_programming_task(task, workspace)

    try:
        from atlas_agent_runtime import AtlasAgent
    except ImportError:
        from agents.atlas_agent_runtime import AtlasAgent

    agent = AtlasAgent(
        base_url=args.server,
        name=args.name,
        execute=execute,
        model="atlas-programming-worker",
        metadata={
            "worker_type": "programming",
            "workspace_root": str(workspace),
            "writes_files": True,
            "executes_remote_commands": False,
            "protocol": "atlas-swarm-v1",
        },
        poll_interval=args.poll_interval,
        heartbeat_interval=10.0,
        accepted_task_types=["programming"],
    )
    print(f"Atlas Swarm Programming Worker")
    print(f"Server: {args.server}")
    print(f"Workspace root: {workspace}")
    print("Mode: programming tasks; file writes only; remote shell execution disabled")
    shutdown_requested = threading.Event()

    def listen_for_shutdown() -> None:
        try:
            while True:
                line = sys.stdin.readline()
                if line == "":
                    shutdown_requested.set()
                    return
                if line.strip() == "atlas_worker_shutdown":
                    shutdown_requested.set()
                    return
        except Exception:
            shutdown_requested.set()

    threading.Thread(
        target=listen_for_shutdown,
        name="atlas-worker-shutdown-listener",
        daemon=True,
    ).start()

    try:
        registration = agent.register()
        print(f"Registered agent: {registration.get('agent_id')}", flush=True)
        agent.start()

        while not shutdown_requested.wait(1):
            pass

        print("\nGracefully stopping programming worker...", flush=True)
        agent.stop()
        return 0
    except KeyboardInterrupt:
        print("\nStopping worker...")
        agent.stop()
        return 0
    except Exception as exc:
        print(f"Worker startup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            agent.stop()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
