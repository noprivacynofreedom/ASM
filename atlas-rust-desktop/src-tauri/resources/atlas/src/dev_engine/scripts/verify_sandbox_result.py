"""Host-side validation and immutable snapshot of a completed Sandbox result."""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atlas_dev_engine import DevWorkspace  # noqa: E402
from windows_sandbox import WindowsSandboxRunner  # noqa: E402

def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and snapshot Windows Sandbox evidence")
    parser.add_argument("workspace", help="12-character Atlas workspace ID")
    parser.add_argument("run_id", help="32-character sandbox run ID")
    args = parser.parse_args()
    project = os.environ.get("ATLAS_DEV_PROJECT_ROOT")
    if not project:
        parser.error("ATLAS_DEV_PROJECT_ROOT must point to the explicitly approved source project")
    engine = DevWorkspace(project, os.environ.get("ATLAS_DEV_ENGINE_HOME"))
    print(json.dumps(WindowsSandboxRunner(engine).verify_result(args.workspace, args.run_id), indent=2))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
