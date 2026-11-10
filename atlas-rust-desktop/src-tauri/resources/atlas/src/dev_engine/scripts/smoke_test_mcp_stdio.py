"""Live MCP SDK v2 stdio smoke test for Atlas Dev Engine.

Run with the same Python interpreter Atlas uses:
  python -m pip install -r requirements-mcp.txt
  python scripts/smoke_test_mcp_stdio.py --project F:\\APP-DEV\\projects\\atlas-chat

This launches the adapter as a child process and creates one disposable test
workspace under ATLAS_DEV_ENGINE_HOME.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import Client, StdioServerParameters


async def run(project: Path, engine_home: Path) -> None:
    adapter = Path(__file__).resolve().parents[1] / "atlas_dev_engine_mcp.py"
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(adapter)],
        env={
            "ATLAS_DEV_PROJECT_ROOT": str(project.resolve()),
            "ATLAS_DEV_ENGINE_HOME": str(engine_home.resolve()),
        },
    )
    async with Client(params) as client:
        tools_result = await client.list_tools()
        names = {tool.name for tool in tools_result.tools}
        required = {"dev_create_workspace", "dev_list_files", "dev_diff",
                    "dev_request_check", "manager_create_plan", "manager_status"}
        missing = required - names
        if missing:
            raise RuntimeError(f"MCP tool registration missing: {sorted(missing)}")
        created = await client.call_tool("dev_create_workspace", {"label": "mcp-live-smoke"})
        if created.is_error:
            raise RuntimeError(created.content)
        payload = json.loads(created.content[0].text)
        workspace = payload["workspace"]
        listed = await client.call_tool("dev_list_files", {"workspace": workspace, "limit": 10})
        if listed.is_error:
            raise RuntimeError(listed.content)
        diff = await client.call_tool("dev_diff", {"workspace": workspace})
        if diff.is_error:
            raise RuntimeError(diff.content)
        diff_payload = json.loads(diff.content[0].text)
        if diff_payload.get("live_repository_changed") is not False:
            raise RuntimeError("Workspace diff did not confirm source project isolation.")
        print(json.dumps({
            "status": "PASS",
            "protocol_version": client.protocol_version,
            "server": getattr(client.server_info, "name", None),
            "tool_count": len(names),
            "workspace": workspace,
            "source_project_changed": False,
        }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="Explicitly approved source project path")
    parser.add_argument("--engine-home", default=os.environ.get(
        "ATLAS_DEV_ENGINE_HOME", str(Path.home() / ".atlas" / "dev-engine")))
    args = parser.parse_args()
    project = Path(args.project)
    if not project.is_dir():
        parser.error(f"Project directory does not exist: {project}")
    asyncio.run(run(project, Path(args.engine_home)))


if __name__ == "__main__":
    main()
