ATLAS DEV ENGINE + MANAGER + MCP ADAPTER — FOUNDATION V1
========================================================

WHAT THIS PACKAGE CONTAINS
--------------------------
1. atlas_dev_engine.py — reusable isolated project workspace engine.
2. atlas_manager.py — persisted task plans, roles, dependencies, task lifecycle,
   isolated workspace per task, and review-bundle handoff.
3. atlas_dev_engine_mcp.py — MCP adapter for workspace and Manager tools.
4. tests/ — local unit tests for the engine and manager.

The engine is not Atlas-only. Instantiate DevWorkspace with any project folder
that the user explicitly selected. It creates disposable copies outside the
source project, allowing agents to inspect, create, modify and delete files in
the copy, compare diffs, and export a review-first handoff ZIP.

CORE API
--------
from atlas_dev_engine import DevWorkspace
from atlas_manager import AtlasManager
engine = DevWorkspace(r"F:\\path\\to\\user-selected-project")
manager = AtlasManager(engine)
run = manager.create_run("Build a website", tasks=[
  {"id":"ui","title":"Build UI","role":"ui_ux","prompt":"Implement the UI"},
  {"id":"tests","title":"Add tests","role":"tester","depends_on":["ui"]}
])

The Manager's run_ready_tasks requires an injected worker callback. This is
deliberate: no fake agent execution is claimed. The model/agent worker adapter
and Atlas UI tool loop are the next integration step. Every task receives a
separate workspace to prevent concurrent agents from editing the same copy.

SUPPORTED FIXED CHECKS (ENGINE API)
-----------------------------------
python_tests, python_compile, npm_build, npm_tests, cargo_check, cargo_tests,
dotnet_test, go_test. The MCP adapter currently queues check requests for host
approval instead of executing project scripts directly.

MCP SETUP
---------
Install dependency into the Python environment used by Atlas:
  python -m pip install -r requirements-mcp.txt

The MCP server requires ATLAS_DEV_PROJECT_ROOT to be explicitly set to a
user-approved project folder. Set ATLAS_DEV_ENGINE_HOME to choose the persistent
workspace/audit location. See mcp-server-entry.jsonc for a disabled example.
The installer does not edit settings.json or enable MCP automatically.

SAFETY BOUNDARIES
-----------------
* Source project is copied; agent file operations are confined to the copy.
* Git metadata, runtime data, settings, secrets, model files, caches and common
  dependency/build directories are excluded from snapshots.
* Relative paths only; traversal is rejected; symlinks are skipped/rejected.
* Text file writes are limited to 2 MB and atomically replaced.
* Deletion exists only inside the disposable workspace.
* No tool applies patches to the original project, commits, pushes, resets,
  cleans, or changes Git refs.
* Handoff ZIP contains changed files, baseline, deleted-file list and evidence.
* MCP has no arbitrary terminal/command execution tool.
* Test/build requests through MCP are queued for host approval, not executed.
* Manager plans persist to disk and every task receives its own workspace.

IMPORTANT EXECUTION LIMITATION
------------------------------
This is an application-level workspace boundary, NOT an operating-system
sandbox. A build/test command can execute project-defined scripts with the
current Windows user's permissions and may access files outside the workspace.
Do not run checks on an untrusted project. Before unattended execution, add an
OS-enforced sandbox (restricted Windows container/VM or dedicated low-privilege
account with restricted filesystem and network access). Allowlisted command
names alone do not make project scripts harmless.

WHAT IS NOT YET OPERATIONAL
---------------------------
* No local model has yet been connected as the Manager's worker callback.
* MCP tools are defined but have not been tested against the installed MCP SDK
  or Atlas's live MCP monitor on Windows.
* Manager does not yet automatically run the plan through the model/tool loop.
* No Atlas UI approval screen exists yet for pending test requests or patch
  application.
* No changes are automatically applied to the source project.

This package establishes the reusable engine, Manager lifecycle and MCP adapter
contracts. It is a foundation, not a claim that autonomous coding agents are
already operational.

AUDIT HARDENING UPDATE — V1.1
-----------------------------
This audited build adds the following safeguards:
* Workspace storage is rejected if it is the source project, inside it, or a
  parent of it. This prevents recursive self-copy and trust-boundary overlap.
* File operations reject symbolic links in every addressed path component;
  the previous post-resolve symlink check could not detect a followed link.
* Manager task plans are limited to 100 tasks and reject malformed or duplicate
  dependency lists.
* Manager run/task state is persisted before worker execution and at task
  boundaries, so an interrupted worker remains visibly marked as running.
* MCP check requests validate the check name and ensure the requested working
  directory exists inside the selected disposable workspace.
* The disabled MCP example now points to the installer's default
  src/dev_engine/atlas_dev_engine_mcp.py location.

AUDIT VALIDATION
----------------
The included test suite passes 13 tests, including new regression coverage for
workspace-root overlap, symlink escapes, malformed dependencies and persisted
in-flight task state. Python compileall also passes.
The MCP SDK is not installed in the audit runtime, so live MCP protocol startup
and Atlas MCP monitor integration remain unverified. Install the pinned-range
requirement (mcp>=1.2,<2) in Atlas's selected Python environment and test the
stdio handshake before enabling this server.

REMAINING SECURITY LIMIT
------------------------
These safeguards protect the file-operation API's normal paths; they do not
turn a workspace into an OS sandbox. Any approved build/test process still
runs with the Windows account's permissions. Do not run untrusted project
scripts without an OS-enforced boundary (restricted VM/container or dedicated
low-privilege account). The source project is never patched automatically.


ATLAS MONITOR INTEGRATION UPDATE — V1.2
---------------------------------------
The MCP monitor integration patch:
* Passes per-server environment variables to child processes, merged over the
  parent environment rather than replacing it.
* Expands {project}, {python}, Windows %VARIABLE%, and portable $VARIABLE
  placeholders in command, cwd, and environment values.
* Keeps stdio protocol messages on stdout and child diagnostics on stderr.
* Tests initialize -> notifications/initialized -> tools/list -> tools/call,
  tool registration, child environment propagation, tool error evidence, and
  owned-child shutdown using a protocol-compatible fake server.
* Updates the adapter to MCP SDK v2.3+ low-level handler registration.

The fake-server integration tests validate the Atlas monitor's JSON-RPC stdio
framing and lifecycle, but they are not a substitute for a live MCP SDK v2.3
handshake. That final test must run in the Windows Python environment selected
by Atlas, where the MCP SDK is installed.


WINDOWS ATLAS CHAT INSTALL / MONITOR WIRING
-------------------------------------------
1. Back up the current Atlas Chat server.py, mcp_monitor.py and settings.json.
2. Install the engine files into:
     F:\\APP-DEV\\projects\\atlas-chat\\src\\dev_engine
3. Replace the Atlas Chat root mcp_monitor.py with the included env-aware
   version. It preserves child-process ownership and adds per-server env
   forwarding plus failed-handshake cleanup.
4. Merge atlas-server-mcp-env.patch into the current server.py only if its
   _mcp_specs block matches the patch context. Otherwise make the same two
   edits manually: import resolve_mcp_server_specs and have _mcp_specs return
   resolve_mcp_server_specs(SETTINGS.get("mcp_servers", []), app_root=HERE,
   python_exe=sys.executable).
5. Merge the object in mcp-server-entry.jsonc into the existing settings.json
   mcp_servers array. Do not replace the whole settings file. Keep enabled=false
   until the SDK smoke test succeeds. Confirm ATLAS_DEV_PROJECT_ROOT points to
   the approved source folder and ATLAS_DEV_ENGINE_HOME is outside it.
6. Install SDK dependencies into the exact Python interpreter used by Atlas:
     python -m pip install -r src\\dev_engine\\requirements-mcp.txt
7. Run:
     python src\\dev_engine\\scripts\\smoke_test_mcp_stdio.py --project F:\\APP-DEV\\projects\\atlas-chat
8. Only after a PASS, set the MCP entry enabled=true and restart Atlas Chat.
   Verify /api/mcp/status?refresh=1 and /api/mcp/tools. Use /api/mcp/call to
   exercise tools through the existing UI/monitor path.

The server.py patch was generated against the server.py inside the supplied
atlas-chat(1).zip snapshot. The user-provided current upload in this turn was
the Dev Engine package, not the full live Atlas Chat repository; therefore
review/merge the small patch rather than replacing server.py wholesale.

LIVE VALIDATION BOUNDARY
------------------------
The 19 local tests pass. They include a fake JSON-RPC stdio child process,
monitor handshake/tool-list/tool-call/environment/stop tests, adapter handler
contract tests against an SDK-v2-shaped harness, and the original engine and
manager tests. The real mcp==2.3.x package is not installed in this runtime,
so the real SDK handshake and Windows Atlas monitor check must be completed
with scripts/smoke_test_mcp_stdio.py on the user's machine. Do not describe
the fake-server tests as a live SDK test.


WORKSPACE INTEGRITY HARDENING — V1.3
------------------------------------
The v1.3 security workstream hardens the isolated workspace boundary without
changing the MCP adapter, MCP monitor, desktop process lifecycle, or host
approval dispatcher.

* Windows reparse points and directory junctions are treated like symlinks.
* Workspace root and every addressed file-path component are checked before
  resolution, preventing link-based path escapes through the workspace API.
* Check execution performs a full workspace-tree preflight and refuses to run
  if an agent-created symlink or junction is present.
* The authoritative workspace baseline is stored under the engine's separate
  metadata/ directory, outside the agent-editable workspace.
* The in-workspace metadata marker is read-only through the workspace API and
  compared byte-for-byte with the canonical copy before workspace operations.
  Tampering causes fail-closed behavior, including diff and handoff.
* Regression tests cover metadata tampering, metadata write/delete attempts,
  symlinked check directories, and workspace-root symlinks.

These are application-level integrity controls, not an OS sandbox. A process
running with the same Windows account can potentially access other user files
or the engine's metadata directory. The host must still enforce OS-level
isolation for untrusted build/test execution.

WINDOWS SANDBOX EXECUTION, AGENT INTEGRATION & EVIDENCE — V1.5
------------------------------------------------
The separate windows_sandbox.py module adds an OS-enforced build/test execution
path using the Windows Sandbox optional Windows feature (Hyper-V-backed guest).
It does not change MCP request dispatch, MCP monitor behavior, desktop process
ownership, or the existing host approval dispatcher.

Security boundary and mounts:
* Windows Sandbox networking, clipboard and vGPU are disabled in the generated
  .wsb configuration; guest memory is capped at 4 GB.
* The host first creates a private per-run staging copy of the agent workspace.
  Only that disposable copy is mounted writable; the agent's live workspace is
  never exposed as a writable guest mount. Symlinks are copied as links and
  rejected before launch. The runner and fixed check configuration are mounted
  read-only. A separate result directory is mounted writable for guest output.
* An optional ATLAS_SANDBOX_TOOLCHAIN_ROOT is mounted read-only at
  C:\\AtlasToolchain. Provision portable toolchains there; the runner adds its
  root and bin directory to PATH. The default Windows Sandbox guest does not
  include Python, Node, Rust, Go or the .NET SDK, so checks requiring these
  tools fail with a clear error until a compatible toolchain is provided.
* The guest runner accepts only the existing fixed CHECKS names. It never
  accepts an arbitrary command, shell fragment, executable path or arguments.
  Guest process timeout uses taskkill /T to terminate the command process tree.
* Host integration seam: the approval dispatcher may call
  windows_sandbox.launch_approved_request(engine, request_file) after it has
  persisted status="approved" in the canonical
  <engine-root>\pending-check-approvals\<request-id>.json record. The helper
  rejects unapproved/noncanonical requests and prevents consuming one approval
  twice. The dispatcher/UI and desktop process lifecycle are not modified.
* Run scripts\launch_approved_sandbox_request.py <approval-record.json> to
  consume an already-approved request. This script never approves requests.
* Run scripts\verify_sandbox_result.py <workspace-id> <run-id> after the guest
  finishes. It validates run identity, allowlisted check identity, status/exit
  code consistency, output sizes, duration and timestamp, then writes a
  host-side SHA-256-bound snapshot and audit event. Snapshots cannot be silently
  replaced by later guest output.
* Evidence retains evidence_trust=guest_report_unverified. Schema validation
  and host-side hashing do not cryptographically attest that the reported
  command actually ran or that output is truthful. Treat PASS as a guest claim;
  independently review results and diffs before accepting the work.

Manual host-approved launch:
  python scripts\\run_windows_sandbox_check.py <workspace-id> python_tests
  python scripts\\run_windows_sandbox_check.py <workspace-id> npm_build --subdir frontend

After the guest finishes, use the verification script above or call
WindowsSandboxRunner.verify_result(workspace_id, run_id) from host code. The
MCP adapter still only queues requests for host approval; this workstream adds
a dispatcher-facing consumption seam without modifying the approval dispatcher
or desktop process lifecycle.

Requirements and limits:
* Windows 10/11 Pro, Enterprise or Education with Windows Sandbox enabled,
  virtualization available, and a reboot after enabling the feature.
* Workspace, control and results folders must be on a local host volume.
* This is VM isolation, not a guarantee against hypervisor vulnerabilities or
  malicious use of explicitly mounted writable folders. Keep the workspace
  disposable and do not mount user profiles, credentials, source repositories
  or broad host directories.
* Windows Sandbox launch/completion has not been exercised in this Linux build
  environment. XML generation and host-side policy are covered by unit tests;
  run the included Windows smoke test on the target PC before relying on it.


V1.5 WORKSTREAM COMPLETION
--------------------------
* Added the host approval-consumption API and CLI bridge without changing the
  MCP adapter, approval dispatcher implementation, or desktop lifecycle.
* Changed sandbox execution to use a fresh per-run staging copy, protecting the
  live agent workspace from guest writes.
* Added strict result schema/identity/consistency validation, bounded output,
  host-side SHA-256 snapshotting, exclusive snapshot creation and audit events.
* Added CLI evidence verification and installer inclusion of the sandbox module
  and scripts.
* Automated validation: 31 unit tests pass in the development environment.
* Windows Sandbox launch and guest toolchain execution remain target-machine
  acceptance tests; this build environment cannot boot Windows Sandbox.
