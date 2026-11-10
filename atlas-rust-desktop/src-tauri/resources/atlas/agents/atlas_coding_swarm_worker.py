"""Local Atlas queue worker for model-backed programming tasks.

Run: py -3 agents/atlas_coding_swarm_worker.py --api http://127.0.0.1:8090
The worker writes generated projects only beneath <project>/swarm-workspaces.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from agents.atlas_agent_runtime import AtlasAgent
from agents.atlas_coding_swarm import run_coding_session


def execute(task: dict) -> dict:
    payload = task.get("payload") or {}
    request = payload.get("request")
    if not isinstance(request, str) or not request.strip() or len(request) > 12000:
        raise ValueError("Task payload.request must contain 1..12000 characters")
    # Workspace is intentionally fixed beneath the project root; API callers
    # cannot supply an arbitrary path or overwrite the source project.
    workspace = ROOT / "swarm-workspaces"
    profile = payload.get("test_profile")
    if profile not in (None, "", "python-unittest", "python-pytest", "node-test"):
        raise ValueError("Unsupported test profile")
    model = payload.get("model")
    if model is not None and (not isinstance(model, str) or len(model) > 200):
        raise ValueError("Invalid model identifier")
    repairs = payload.get("max_repairs", 1)
    if not isinstance(repairs, int) or not 0 <= repairs <= 3:
        raise ValueError("max_repairs must be an integer from 0 to 3")
    return run_coding_session(request, workspace, model=model,
                              test_profile=profile or None, max_repairs=repairs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Atlas model-backed programming queue worker")
    parser.add_argument("--api", default="http://127.0.0.1:8090")
    parser.add_argument("--name", default="Atlas Local Programming Worker")
    parser.add_argument("--model", default="")
    args = parser.parse_args()
    agent = AtlasAgent(args.api, args.name, execute, model=args.model,
                       metadata={"capability": "model-backed-programming", "workspace_policy": "project/swarm-workspaces"},
                       accepted_task_types=["programming"])
    print("Registering Atlas programming worker with", args.api, flush=True)
    agent.start()
    print("Worker online. Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            agent._stop.wait(1)
    except KeyboardInterrupt:
        print("Stopping this worker…", flush=True)
        agent.stop()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
