"""Consume a host-approved Atlas check request and launch it in Windows Sandbox.

The approval UI/dispatcher must first persist status="approved" in the request
JSON. This script does not approve requests and does not modify dispatcher code.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atlas_dev_engine import DevWorkspace  # noqa: E402
from windows_sandbox import launch_approved_request  # noqa: E402

def main() -> int:
    parser = argparse.ArgumentParser(description="Launch an already-approved check in Windows Sandbox")
    parser.add_argument("request_file", help="Persisted host approval request JSON")
    args = parser.parse_args()
    project = os.environ.get("ATLAS_DEV_PROJECT_ROOT")
    if not project:
        parser.error("ATLAS_DEV_PROJECT_ROOT must point to the explicitly approved source project")
    engine = DevWorkspace(project, os.environ.get("ATLAS_DEV_ENGINE_HOME"))
    result = launch_approved_request(engine, args.request_file)
    print(json.dumps(result, indent=2))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
