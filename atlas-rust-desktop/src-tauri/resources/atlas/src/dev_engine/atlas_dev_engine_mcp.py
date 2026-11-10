"""MCP adapter for Atlas Dev Engine and Manager.

Project root is supplied explicitly by ATLAS_DEV_PROJECT_ROOT. No default F:
path is assumed, and no arbitrary shell/terminal or live-project write tool is
exposed. Test commands are request-only until a trusted host approval UI exists.
"""
from __future__ import annotations
import asyncio, json, os, time, uuid
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent, Tool
from atlas_dev_engine import CHECKS, DevWorkspace, WorkspaceError, _safe_rel
from atlas_manager import AtlasManager, ManagerError

project_root = os.environ.get("ATLAS_DEV_PROJECT_ROOT")
if not project_root:
    raise RuntimeError("Set ATLAS_DEV_PROJECT_ROOT to the user-approved project folder before starting this MCP server.")
engine_root = os.environ.get("ATLAS_DEV_ENGINE_HOME")
ENGINE = DevWorkspace(project_root, engine_root)
MANAGER = AtlasManager(ENGINE)
def tool(name, description, properties, required):
    return Tool(name=name, description=description,
        input_schema={"type":"object","properties":properties,"required":required})

TOOLS = [
 tool("dev_create_workspace", "Create a disposable copy of the explicitly configured project. Excludes Git metadata, secrets, settings, runtime data, models and dependencies.", {"label":{"type":"string"}}, []),
 tool("dev_list_files", "List files in an isolated workspace.", {"workspace":{"type":"string"},"limit":{"type":"integer"}}, ["workspace"]),
 tool("dev_read_file", "Read a UTF-8 file from an isolated workspace.", {"workspace":{"type":"string"},"path":{"type":"string"}}, ["workspace","path"]),
 tool("dev_write_file", "Create or modify a file only inside an isolated workspace. Does not modify the source project.", {"workspace":{"type":"string"},"path":{"type":"string"},"content":{"type":"string"}}, ["workspace","path","content"]),
 tool("dev_delete_file", "Delete a regular file only inside an isolated workspace. Never deletes source-project files.", {"workspace":{"type":"string"},"path":{"type":"string"}}, ["workspace","path"]),
 tool("dev_diff", "Compare an isolated workspace against its baseline, including added, modified and deleted paths plus test evidence.", {"workspace":{"type":"string"}}, ["workspace"]),
 tool("dev_evidence", "Read recorded test/build evidence for an isolated workspace.", {"workspace":{"type":"string"}}, ["workspace"]),
 tool("dev_export_handoff", "Export a review-first ZIP with changed files, baseline, deletion list and evidence. Does not apply changes.", {"workspace":{"type":"string"}}, ["workspace"]),
 tool("manager_create_plan", "Create a persisted task plan with agent roles and dependencies. This plans work; it does not claim agents have run.", {"goal":{"type":"string"},"project_label":{"type":"string"},"tasks":{"type":"array","items":{"type":"object","properties":{"id":{"type":"string"},"title":{"type":"string"},"prompt":{"type":"string"},"role":{"type":"string","enum":["planner","architect","coder","ui_ux","tester","reviewer","researcher","general"]},"depends_on":{"type":"array","items":{"type":"string"}}},"required":["title"]}}}, ["goal","tasks"]),
 tool("manager_status", "Read a persisted Manager run and task statuses.", {"run":{"type":"string"}}, ["run"]),
 tool("manager_handoff", "Export review bundles for workspaces associated with a Manager run. Never applies changes to the source project.", {"run":{"type":"string"}}, ["run"]),
 tool("dev_request_check", "Queue a test/build request for explicit host approval. This tool does not execute project scripts.", {"workspace":{"type":"string"},"check":{"type":"string","enum":["python_tests","python_compile","npm_build","npm_tests","cargo_check","cargo_tests","dotnet_test","go_test"]},"subdir":{"type":"string"}}, ["workspace","check"]),
]

async def handle_list_tools(ctx, params) -> ListToolsResult:
    return ListToolsResult(tools=TOOLS)


async def handle_call_tool(ctx, params: CallToolRequestParams) -> CallToolResult:
    """Dispatch one registered tool and return errors as MCP tool results."""
    name = params.name
    a = params.arguments or {}
    try:
        if name == "dev_create_workspace":
            result = ENGINE.create(a.get("label", "agent-task"))
        elif name == "dev_list_files":
            result = ENGINE.list_files(a["workspace"], a.get("limit", 500))
        elif name == "dev_read_file":
            result = ENGINE.read_file(a["workspace"], a["path"])
        elif name == "dev_write_file":
            result = ENGINE.write_file(a["workspace"], a["path"], a["content"])
        elif name == "dev_delete_file":
            result = ENGINE.delete_file(a["workspace"], a["path"])
        elif name == "dev_diff":
            result = ENGINE.diff(a["workspace"])
        elif name == "dev_evidence":
            result = ENGINE.evidence(a["workspace"])
        elif name == "dev_export_handoff":
            result = {"bundle": ENGINE.export_patch_bundle(a["workspace"]), "applied": False}
        elif name == "manager_create_plan":
            result = MANAGER.create_run(a["goal"], a.get("project_label", "project"), a["tasks"])
        elif name == "manager_status":
            result = MANAGER.summary(a["run"])
        elif name == "manager_handoff":
            result = MANAGER.handoff(a["run"])
        elif name == "dev_request_check":
            ws = ENGINE._workspace(a["workspace"])
            check = a.get("check")
            if check not in CHECKS:
                raise WorkspaceError("Unsupported check request.")
            subdir = a.get("subdir", ".")
            rel = Path(".") if subdir in ("", ".") else _safe_rel(subdir)
            cwd = (ws / rel).resolve()
            if cwd != ws and ws not in cwd.parents:
                raise WorkspaceError("Check directory escapes workspace.")
            if not cwd.is_dir():
                raise WorkspaceError("Check directory does not exist.")
            request_id = uuid.uuid4().hex
            folder = ENGINE.root / "pending-check-approvals"
            folder.mkdir(parents=True, exist_ok=True)
            result = {"id": request_id, "workspace": a["workspace"], "check": check,
                      "subdir": rel.as_posix() if str(rel) != "." else ".",
                      "status": "awaiting_host_approval", "created_at": time.time(),
                      "warning": "Project build/test scripts execute code. Host approval and OS isolation are required."}
            (folder / f"{request_id}.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8")
        else:
            raise WorkspaceError("Unknown tool.")
        payload = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
        return CallToolResult(content=[TextContent(type="text", text=payload)], is_error=False)
    except Exception as exc:
        error = json.dumps({"error": f"{type(exc).__name__}: {exc}",
                            "source_project_changed": False}, ensure_ascii=False)
        return CallToolResult(content=[TextContent(type="text", text=error)], is_error=True)


server = Server(
    "atlas-dev-engine",
    version="1.2.0",
    on_list_tools=handle_list_tools,
    on_call_tool=handle_call_tool,
)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )

if __name__ == "__main__": asyncio.run(main())
