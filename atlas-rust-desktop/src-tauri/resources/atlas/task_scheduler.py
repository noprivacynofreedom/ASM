"""Local Task Scheduler for Atlas Chat (Phase 2B — Odysseus integration).

Consent-gated local recurring prompts and health checks.
Persists schedule definitions in <DATA_DIR>/.atlas/scheduler.json and run logs
in <DATA_DIR>/.atlas/scheduler_history.jsonl.

Safety boundaries:
- Global scheduler starts PAUSED by default until explicitly resumed by the user.
- Tasks start DISABLED unless explicitly enabled.
- Tasks can only generate local text or local health snapshots;
  they never send emails, never delete files, and never execute shell commands.

Standard library only.
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
from typing import Any, Callable

import cloud_llm
import llm
import optional_modules

VALID_KINDS = ("prompt", "health_check")
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 10080  # 7 days
MAX_TASKS = 32

_LOCK = threading.Lock()
_TICKER_STARTED = False


def _state_path(data_dir: str) -> str:
    folder = os.path.join(data_dir, ".atlas")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "scheduler.json")


def _history_path(data_dir: str) -> str:
    folder = os.path.join(data_dir, ".atlas")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "scheduler_history.jsonl")


def _default_state() -> dict[str, Any]:
    return {"paused": True, "tasks": []}


def load_state(data_dir: str) -> dict[str, Any]:
    path = _state_path(data_dir)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return {
                "paused": bool(raw.get("paused", True)),
                "tasks": [t for t in (raw.get("tasks") or []) if isinstance(t, dict)],
            }
    except (OSError, ValueError):
        pass
    return _default_state()


def _save_state(data_dir: str, state: dict[str, Any]) -> None:
    path = _state_path(data_dir)
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".sched-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
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


def _append_history(data_dir: str, entry: dict[str, Any]) -> None:
    path = _history_path(data_dir)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_history(data_dir: str, limit: int = 30) -> list[dict[str, Any]]:
    path = _history_path(data_dir)
    rows: list[dict[str, Any]] = []
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            rows.append(obj)
                    except ValueError:
                        continue
        except OSError:
            pass
    return list(reversed(rows[-max(1, int(limit)) :]))


def status_view(data_dir: str, history_limit: int = 25) -> dict[str, Any]:
    with _LOCK:
        st = load_state(data_dir)
        hist = read_history(data_dir, limit=history_limit)
    return {"paused": st["paused"], "tasks": st["tasks"], "history": hist}


def set_paused(data_dir: str, paused: bool) -> dict[str, Any]:
    with _LOCK:
        st = load_state(data_dir)
        st["paused"] = bool(paused)
        _save_state(data_dir, st)
        return {"paused": st["paused"], "tasks": st["tasks"]}


def upsert_task(data_dir: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create, update, toggle, or delete a scheduled task."""
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    action = str(payload.get("action") or "save").strip().lower()

    with _LOCK:
        st = load_state(data_dir)
        tasks = list(st["tasks"])

        if action == "delete":
            tid = str(payload.get("id") or "").strip()
            before = len(tasks)
            tasks = [t for t in tasks if t.get("id") != tid]
            if len(tasks) == before:
                raise KeyError("Scheduled task not found")
            st["tasks"] = tasks
            _save_state(data_dir, st)
            return {"deleted": tid, "tasks": tasks}

        if action == "toggle":
            tid = str(payload.get("id") or "").strip()
            hit = next((t for t in tasks if t.get("id") == tid), None)
            if not hit:
                raise KeyError("Scheduled task not found")
            enabled = bool(payload.get("enabled", not hit.get("enabled")))
            hit["enabled"] = enabled
            if enabled:
                hit["next_run_at"] = time.time() + int(hit.get("interval_minutes") or 60) * 60
            st["tasks"] = tasks
            _save_state(data_dir, st)
            return {"task": hit, "tasks": tasks}

        name = str(payload.get("name") or "").strip()[:100]
        if not name:
            raise ValueError("Task name is required")
        kind = str(payload.get("kind") or "prompt").strip().lower()
        if kind not in VALID_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(VALID_KINDS)}")
        prompt = str(payload.get("prompt") or "").strip()[:4000]
        if kind == "prompt" and not prompt:
            raise ValueError("Prompt or topic is required for this task kind")
        try:
            interval = int(payload.get("interval_minutes") or 60)
        except (TypeError, ValueError) as exc:
            raise ValueError("interval_minutes must be an integer") from exc
        if interval < MIN_INTERVAL_MINUTES or interval > MAX_INTERVAL_MINUTES:
            raise ValueError(f"interval_minutes must be between {MIN_INTERVAL_MINUTES} and {MAX_INTERVAL_MINUTES}")

        model = str(payload.get("model") or "tasks").strip()[:80] or "tasks"
        enabled = bool(payload.get("enabled", False))
        now = time.time()

        tid = str(payload.get("id") or "").strip()
        existing = next((t for t in tasks if t.get("id") == tid), None) if tid else None
        if existing:
            existing.update({
                "name": name,
                "kind": kind,
                "prompt": prompt,
                "model": model,
                "interval_minutes": interval,
                "enabled": enabled,
                "next_run_at": now + interval * 60 if enabled else existing.get("next_run_at"),
            })
            task = existing
        else:
            if len(tasks) >= MAX_TASKS:
                raise ValueError(f"Maximum of {MAX_TASKS} scheduled tasks reached")
            task = {
                "id": "sch-" + secrets.token_hex(5),
                "name": name,
                "kind": kind,
                "prompt": prompt,
                "model": model,
                "interval_minutes": interval,
                "enabled": enabled,
                "created_at": now,
                "last_run_at": None,
                "last_status": "never",
                "next_run_at": now + interval * 60 if enabled else None,
            }
            tasks.insert(0, task)

        st["tasks"] = tasks
        _save_state(data_dir, st)
        return {"task": task, "tasks": tasks}


def _default_prompt_runner(model: str, prompt: str) -> str:
    if cloud_llm.is_cloud_model(model):
        comp, _ = cloud_llm.chat_completion(
            {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 900},
            timeout=90,
        )
        return str((comp.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
    return str(llm.call_llm(prompt, temperature=0.3, max_tokens=900, model=model or "tasks", timeout=90) or "").strip()


def run_task_now(
    data_dir: str,
    task_id: str,
    *,
    prompt_runner: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """Execute one scheduled task immediately and record its output in scheduler_history.jsonl."""
    with _LOCK:
        st = load_state(data_dir)
        task = next((t for t in st["tasks"] if t.get("id") == str(task_id or "").strip()), None)
        if not task:
            raise KeyError("Scheduled task not found")
        task_copy = dict(task)

    t0 = time.monotonic()
    status = "ok"
    output = ""
    error = ""
    try:
        kind = task_copy["kind"]
        if kind == "health_check":
            local_ready = llm.model_ready()
            cloud_ready = cloud_llm.free_providers()
            output = (
                f"Local llama-swap reachable: {'yes' if local_ready else 'no'}\n"
                f"Ready free cloud providers: {', '.join(cloud_ready) if cloud_ready else 'none'}"
            )
        else:
            runner = prompt_runner or _default_prompt_runner
            output = runner(task_copy.get("model") or "tasks", task_copy["prompt"])
    except Exception as exc:
        status = "error"
        error = str(exc)[:400]

    duration_ms = int(round((time.monotonic() - t0) * 1000))
    finished_at = time.time()
    entry = {
        "run_id": "srun-" + secrets.token_hex(5),
        "task_id": task_copy["id"],
        "task_name": task_copy["name"],
        "kind": task_copy["kind"],
        "model": task_copy.get("model") or "",
        "ts": finished_at,
        "duration_ms": duration_ms,
        "status": status,
        "output": output[:6000],
        "error": error,
    }

    with _LOCK:
        st = load_state(data_dir)
        for t in st["tasks"]:
            if t.get("id") == task_copy["id"]:
                t["last_run_at"] = finished_at
                t["last_status"] = status
                if t.get("enabled"):
                    t["next_run_at"] = finished_at + int(t.get("interval_minutes") or 60) * 60
                break
        _save_state(data_dir, st)
        _append_history(data_dir, entry)

    return entry


def tick_due_tasks(
    data_dir: str,
    settings: dict[str, Any] | None = None,
    *,
    prompt_runner: Callable[[str, str], str] | None = None,
) -> list[dict[str, Any]]:
    """Run any enabled tasks whose next_run_at <= now when scheduler module is active and unpaused."""
    if not optional_modules.is_enabled(settings, "scheduler"):
        return []
    now = time.time()
    with _LOCK:
        st = load_state(data_dir)
        if st.get("paused", True):
            return []
        due_ids = [
            t["id"]
            for t in st["tasks"]
            if t.get("enabled") and t.get("next_run_at") and float(t["next_run_at"]) <= now
        ]
    results = []
    for tid in due_ids:
        try:
            results.append(run_task_now(data_dir, tid, prompt_runner=prompt_runner))
        except Exception:
            pass
    return results


def start_background_ticker(data_dir: str, settings_getter: Callable[[], dict[str, Any]]) -> None:
    """Start one lightweight daemon thread that checks due tasks every 15 seconds."""
    global _TICKER_STARTED
    with _LOCK:
        if _TICKER_STARTED:
            return
        _TICKER_STARTED = True

    def _loop():
        while True:
            time.sleep(15)
            try:
                tick_due_tasks(data_dir, settings_getter())
            except Exception:
                pass

    threading.Thread(target=_loop, daemon=True, name="atlas-scheduler-tick").start()
