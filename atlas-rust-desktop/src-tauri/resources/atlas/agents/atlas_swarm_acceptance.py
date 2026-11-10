"""Command-line entry point for the local Atlas coding Swarm."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from atlas_coding_swarm import run_coding_session

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--workspace", default="swarm-workspaces")
    parser.add_argument("--model", default=None)
    parser.add_argument("--test-profile", choices=["python-unittest","python-pytest","node-test"])
    parser.add_argument("--max-repairs", type=int, default=2)
    args = parser.parse_args()
    result = run_coding_session(args.request, Path(args.workspace), args.model, args.test_profile, args.max_repairs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2

if __name__ == "__main__":
    raise SystemExit(main())
