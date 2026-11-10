# Atlas MCP Audit (Phase 1, read-only, no fixes applied)

Audited 2026-11-10 on branch `main` (CLAUDE.md warns `main` may be an OLD branch: confirm the real app branch before Phase 3).

## Corrections to the handoff
- `resources/atlas/server.py` is NOT a copy of `src/mcp_commander.py`. It is the Atlas HTTP backend (port 8090). Different program.
- `src/mcp_commander.py` is NOT the file with the `HERE` write bug. `mcp_agent.py` is.
- "Duplicate" is real, but between the repo root and `resources/atlas/` (plus `Atlas Chat/atlas/`, `target/{debug,release}/atlas/`, `release/`, `backups/`).

## File table
| File | Purpose | Creates/Reads | Depends on | Active? |
|---|---|---|---|---|
| `src/mcp_commander.py` | Stdio MCP server "atlas-commander", READ-ONLY tools: atlas_project_status, atlas_list_files, atlas_read_file, list/read/verify_workspace_file. No write tool. | Reads files under `ROOT` = env `ATLAS_WORKSPACE` else parent of `src/` | stdlib only | YES: the only server in `settings.json` |
| `server.py` (HTTP backend) | Proxy/chat API on 8090; injects system prompts, docs, runs MCP tool loop | settings.json, data.json, prompts/, workspace dir | mcp_monitor, mcp_chat, config, llm, docsearch, book_tools | YES (spawned by Rust `process_supervisor.rs:1128` as `root/server.py`) |
| `mcp_monitor.py` | Launches MCP servers from `settings.json` `mcp_servers`, substitutes `{python}`,`{project}`,`{workspace}`, sets `ATLAS_WORKSPACE` env only if workspace given | Popen child processes | settings.json | YES |
| `mcp_chat.py` | Tool loop: calls llama-swap, executes tools, re-posts. **Appends `role:system` messages at END** (lines 212, 414) | HTTP to upstream 8080 | mcp_monitor | YES |
| `mcp_agent.py` | A SECOND, separate MCP server "atlas-chat-rust-builder": `run_terminal_command`, `write_project_file`. Both use `cwd/target = HERE` (its own folder), not project root. Unrestricted shell. | writes to its own dir | `mcp` pip pkg | NO: not in settings.json; only referenced by `dev_cycle.py` compile check. Dead/dormant |
| `config.py` | Settings loader; `WORKSPACE_DIR` from env `ATLAS_CHAT_WORKSPACE` or settings `workspace_dir` | settings.json | stdlib | YES (identical hash in root, src/, resources) |
| `tauri.conf.json` | Bundles `resources/atlas` -> `atlas` in NSIS installer; `beforeBuildCommand: npm run build`. **No step copies Python files in.** | - | - | YES |
| `Cargo.toml` | Rust deps only. No build script copying Python. | - | - | YES |
| `process_supervisor.rs` | Finds runtime root: env `ATLAS_RUNTIME_ROOT`, then `ATLAS_PROJECT_ROOT`, then `resources/atlas` next to exe (lines 423-445); spawns python `server.py` | | | YES |

## Phase 1B answers
- One MCP server or two? **One running** (atlas-commander). `mcp_agent.py` exists but is never launched.
- Which Python files does Tauri package? Everything in `src-tauri/resources/atlas/` (a directory mapping, so whatever is in that folder, including its own `src/mcp_commander.py`, runtime/python).
- Copies or symlinks? **Plain copies.** Zero symlinks found.
- When is server.py copied to resources/? **Never automatically.** `build-release.ps1` only checks bundled Python exists; no copy step. Resources is hand-edited (CLAUDE.md says it is the authoritative one). Hence drift.

## Duplication / drift (md5)
- `src/mcp_commander.py` == resources == `Atlas Chat/atlas` == target/release == target/debug copies: IDENTICAL. Safe.
- `config.py`, `mcp_chat.py`, `mcp_monitor.py`, `mcp_agent.py`, `llm.py`: root == resources: identical.
- **`server.py`: root != resources** (resources has richer event projection around line 613). `src/server.py` and `release/server.py` are each different again. Three+ divergent server.py versions.
- `Atlas Chat/atlas/server.py` == resources (an installed copy).
- `src/` also holds stale `server.py`, `config.py`, `llm.py`, `test_local_model.py`.

## Answers to the critical issues (hypotheses, to verify in Phase 2)
1. **Jinja "System message must be at the beginning"**: strong suspect is `mcp_chat.py:212` and `:414`, which `append` a system message after user/assistant/tool messages. Strict templates (Qwen etc.) reject that. Secondary: `server.py _add_docs` only checks `msgs[0]`, and `_inject` merges into the first system found anywhere, which can leave it non-first. Fix idea (not applied): send those instructions as the first system message or as a user message.
2. **Which file runs**: packaged app runs `resources/atlas/server.py`, which launches `resources/atlas/src/mcp_commander.py`. They are different programs, not duplicates of each other.
3. **File-writing bug**: only in dormant `mcp_agent.py` (`HERE`). The live commander has no write tool, so a model "writing files" through Atlas currently cannot; that is itself a gap.
4. **Project root**: commander uses `ATLAS_WORKSPACE`, set by mcp_monitor only if a workspace is given; else falls back to the parent of `src/` (the install dir when packaged). Rust uses `ATLAS_PROJECT_ROOT`/`ATLAS_RUNTIME_ROOT`; config.py uses `ATLAS_CHAT_WORKSPACE`. Three names, three meanings.

## Proposed Phase 3 (awaiting your approval)
1. Declare `resources/atlas/` the single source (matches CLAUDE.md). Diff-merge root `server.py` into it first (nothing lost).
2. Remove stale root/`src/`/`release/` copies (git history keeps them); keep one unambiguous `mcp_commander.py`.
3. Fix message ordering in `mcp_chat.py` and `_add_docs`; log the outgoing payload once to confirm.
4. One env var `ATLAS_PROJECT_ROOT` for read, and a separate `ATLAS_WORKSPACE` for writes; decide whether to give the commander a safe write tool and retire `mcp_agent.py`.
