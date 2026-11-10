"""Atlas Node task dispatch adapter.

Uses the existing authenticated Atlas Ops queue. A remote node must run an
agent explicitly accepting the requested task type. This adapter does not
pretend a node executed a task merely because it was queued.
"""
from __future__ import annotations
import json, urllib.request, urllib.error

def submit_node_task(server: str, task_type: str, payload: dict, priority: int = 0) -> dict:
    if not task_type.startswith("node_"):
        raise ValueError("Remote task types must use the node_ namespace")
    body = json.dumps({"type": task_type, "priority": priority, "payload": payload}).encode()
    req = urllib.request.Request(server.rstrip("/") + "/api/ops/tasks", data=body,
                                 headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Atlas Node gateway unavailable: {exc}") from exc
    return {"queued": True, "execution_verified": False, **result}
