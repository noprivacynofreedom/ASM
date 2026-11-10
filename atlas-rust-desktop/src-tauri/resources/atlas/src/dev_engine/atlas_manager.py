"""Task manager/orchestrator for Atlas Dev Engine.

The manager owns task plans and lifecycle. Model/agent execution is injected so
this module can be tested without a model server and later connected to Atlas
llm.py and MCP without granting agents direct host filesystem access.
"""
from __future__ import annotations
import json, re, time, uuid
from pathlib import Path
from typing import Any, Callable
from atlas_dev_engine import DevWorkspace, WorkspaceError

ROLES = {"planner", "architect", "coder", "ui_ux", "tester", "reviewer", "researcher", "general"}
STATUSES = {"planned", "ready", "running", "completed", "blocked", "failed", "cancelled"}

class ManagerError(RuntimeError):
    pass

class AtlasManager:
    def __init__(self, engine: DevWorkspace, state_root: str | Path | None = None):
        self.engine = engine
        self.state_root = Path(state_root or (engine.root / "manager"))
        self.state_root.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{12}", str(run_id)):
            raise ManagerError("Invalid run ID.")
        p = self.state_root / f"{run_id}.json"
        if not p.is_file():
            raise ManagerError("Run not found.")
        return p

    def _load(self, run_id: str) -> dict[str, Any]:
        return json.loads(self._path(run_id).read_text(encoding="utf-8"))

    def _save(self, run: dict[str, Any]) -> None:
        run["updated_at"] = time.time()
        p = self.state_root / f"{run['id']}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)

    def create_run(self, goal: str, project_label: str = "project", tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        goal = str(goal).strip()
        if not goal or len(goal) > 12000:
            raise ManagerError("Goal must contain 1–12000 characters.")
        run_id = uuid.uuid4().hex[:12]
        if tasks is not None and not isinstance(tasks, list):
            raise ManagerError("Tasks must be supplied as a list.")
        if tasks is not None and len(tasks) > 100:
            raise ManagerError("A run is limited to 100 tasks.")
        normalized = []
        seen = set()
        for i, item in enumerate(tasks or []):
            if not isinstance(item, dict):
                raise ManagerError("Every task must be an object.")
            tid = str(item.get("id") or f"task-{i+1}")
            if tid in seen or not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", tid):
                raise ManagerError(f"Invalid or duplicate task id: {tid}")
            seen.add(tid)
            role = str(item.get("role", "general"))
            if role not in ROLES:
                raise ManagerError(f"Unsupported agent role: {role}")
            title = str(item.get("title", "")).strip()
            prompt = str(item.get("prompt", title)).strip()
            if not title or not prompt:
                raise ManagerError("Every task needs a title and prompt.")
            raw_deps = item.get("depends_on", [])
            if not isinstance(raw_deps, list) or any(not isinstance(dep, str) for dep in raw_deps):
                raise ManagerError(f"Dependencies for {tid} must be a list of task IDs.")
            deps = list(raw_deps)
            if len(deps) != len(set(deps)):
                raise ManagerError(f"Duplicate dependencies for task {tid}.")
            normalized.append({"id": tid, "title": title[:160], "prompt": prompt[:12000],
                "role": role, "depends_on": deps, "status": "planned", "workspace": None,
                "result": None, "error": None, "created_at": time.time()})
        for task in normalized:
            unknown = set(task["depends_on"]) - seen
            if unknown: raise ManagerError(f"Unknown dependencies for {task['id']}: {sorted(unknown)}")
            if task["id"] in task["depends_on"]: raise ManagerError("A task cannot depend on itself.")
        self._assert_acyclic(normalized)
        run = {"id": run_id, "goal": goal, "project_label": str(project_label)[:80],
               "status": "planned", "tasks": normalized, "created_at": time.time(),
               "updated_at": time.time(), "approval_required_for_handoff": True}
        self._save(run)
        return self.summary(run_id)

    @staticmethod
    def _assert_acyclic(tasks: list[dict[str, Any]]) -> None:
        graph = {t["id"]: set(t["depends_on"]) for t in tasks}
        visiting, visited = set(), set()
        def visit(node):
            if node in visiting: raise ManagerError("Task dependencies contain a cycle.")
            if node in visited: return
            visiting.add(node)
            for dep in graph[node]: visit(dep)
            visiting.remove(node); visited.add(node)
        for node in graph: visit(node)

    def summary(self, run_id: str) -> dict[str, Any]:
        run = self._load(run_id)
        counts = {s: sum(1 for t in run["tasks"] if t["status"] == s) for s in STATUSES}
        return {"id": run["id"], "goal": run["goal"], "status": run["status"],
                "tasks": run["tasks"], "counts": counts,
                "approval_required_for_handoff": True}

    def run_ready_tasks(self, run_id: str, worker: Callable[[dict[str, Any], str, DevWorkspace], dict[str, Any]],
                        max_tasks: int = 1) -> dict[str, Any]:
        """Execute ready tasks serially; each gets its own independent workspace.

        worker(task, workspace_id, engine) must perform the actual agent work and
        return a structured result. No worker is supplied by default.
        """
        if not callable(worker): raise ManagerError("An agent worker adapter is required; no fake execution is performed.")
        run = self._load(run_id)
        completed = {t["id"] for t in run["tasks"] if t["status"] == "completed"}
        allowance = max(1, min(int(max_tasks), 10))
        executed = 0
        run["status"] = "running"
        self._save(run)  # Persist the run before handing control to an external worker.
        for task in run["tasks"]:
            if executed >= allowance: break
            if task["status"] not in ("planned", "ready"): continue
            if not set(task["depends_on"]).issubset(completed):
                task["status"] = "blocked"
                continue
            task["status"] = "running"
            task["started_at"] = time.time()
            self._save(run)  # A crash must not make an in-flight task look unstarted.
            try:
                created = self.engine.create(f"{run['project_label']} - {task['id']} - {task['title']}")
                task["workspace"] = created["workspace"]
                self._save(run)
                result = worker(dict(task), created["workspace"], self.engine)
                if not isinstance(result, dict): raise ManagerError("Agent worker must return a result object.")
                task["result"] = result
                task["status"] = "completed" if result.get("status") == "completed" else "failed"
                task["error"] = None if task["status"] == "completed" else result.get("error", "Worker did not report completed status.")
                if task["status"] == "completed": completed.add(task["id"])
            except Exception as exc:
                task["status"] = "failed"
                task["error"] = f"{type(exc).__name__}: {exc}"
            task["finished_at"] = time.time()
            self._save(run)
            executed += 1
        for task in run["tasks"]:
            if task["status"] == "blocked" and set(task["depends_on"]).issubset(completed): task["status"] = "planned"
        states = {t["status"] for t in run["tasks"]}
        if not run["tasks"]: run["status"] = "planned"
        elif states <= {"completed"}: run["status"] = "completed"
        elif "running" in states: run["status"] = "running"
        elif "failed" in states: run["status"] = "needs_attention"
        else: run["status"] = "ready"
        self._save(run)
        return self.summary(run_id)

    def handoff(self, run_id: str) -> list[dict[str, Any]]:
        """Produce review bundles; never applies changes to source projects."""
        run = self._load(run_id)
        outputs = []
        for task in run["tasks"]:
            wid = task.get("workspace")
            if not wid: continue
            outputs.append({"task": task["id"], "status": task["status"],
                            "diff": self.engine.diff(wid),
                            "bundle": self.engine.export_patch_bundle(wid)})
        return outputs
