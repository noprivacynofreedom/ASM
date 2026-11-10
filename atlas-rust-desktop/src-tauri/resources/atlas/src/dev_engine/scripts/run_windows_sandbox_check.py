"""Launch one fixed Atlas check inside Windows Sandbox after host approval.

Example (PowerShell):
  $env:ATLAS_DEV_PROJECT_ROOT = 'F:\\APP-DEV\\projects\\atlas-chat'
  $env:ATLAS_DEV_ENGINE_HOME = "$env:LOCALAPPDATA\\Atlas\\DevWorkspaces"
  python scripts\\run_windows_sandbox_check.py <workspace-id> python_tests

This script does not accept arbitrary commands and does not patch the source repo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atlas_dev_engine import DevWorkspace  # noqa: E402
from windows_sandbox import WindowsSandboxRunner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an allowlisted check in Windows Sandbox")
    parser.add_argument("workspace", help="12-character Atlas disposable workspace ID")
    parser.add_argument("check", choices=["python_tests", "python_compile", "npm_build", "npm_tests",
                                           "cargo_check", "cargo_tests", "dotnet_test", "go_test"])
    parser.add_argument("--subdir", default=".", help="Relative working directory inside workspace")
    args = parser.parse_args()
    project = os.environ.get("ATLAS_DEV_PROJECT_ROOT")
    if not project:
        parser.error("ATLAS_DEV_PROJECT_ROOT must point to the explicitly approved source project")
    engine = DevWorkspace(project, os.environ.get("ATLAS_DEV_ENGINE_HOME"))
    result = WindowsSandboxRunner(engine).launch(args.workspace, args.check, args.subdir)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
