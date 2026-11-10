# MCP and request handling: bugs found and fixed (2026-11-10)

Branch: `fix/mcp-request-hardening`. Code is in `atlas-rust-desktop/src-tauri/resources/atlas/` (the shipped copy).
Tests: `tests/test_mcp_hardening.py` (24 tests). Against the old code 22 of 23 original tests failed; all pass now.

## Read first
- This branch has a first commit marked `SNAPSHOT (not my work)`. It is an exact copy of another session's
  uncommitted edits (`mcp_chat.py`, `server.py`, `src/mcp_commander.py`, tests). It exists only so the fixes sit on
  top of that code. Commit that other work on `main` first. The snapshot is then dropped (rebase).
- Not tested here: the Windows app itself (Tauri build, installer). Tests ran on Linux with Python 3.12.
  The Windows UTF-8 fix was tested by forcing `PYTHONIOENCODING=ascii`, not on a real cp1252 console.
- One test fails before and after, and is not MCP: `test_docsearch ... cached_postings_refresh` (file time stamps).

## Bugs and fixes
| # | Where | Bug (what the user sees) | Fix |
|---|---|---|---|
| 1 | `server.py` bot files | `GET`/`POST /api/bot/<id>/files` always answered 404. The code read `parts[2]` (the bot id) as `"files"`, and used `"bot"` as the id. | One route parser `_bot_files_route`. 400 for bad id/name/JSON, 413 over 1 MB, name rules (no `..`, `/`, `\`, `:`). |
| 2 | `server.py` `_body` | A bad `Content-Length` dropped the connection. No size limit. Chunked bodies were read as empty. | 400 / 413 with a message. Limit 192 MB (a 100 MB book is about 134 MB of base64). |
| 3 | `server.py` chat | An online MCP server with no tools made every chat fail with 502. | `NoLiveTools`: fall back to plain chat. |
| 4 | `server.py` chat | A server that could not start was re-tried on EVERY chat message (each waited for the timeout). A server that died while another was up was never restarted. | `MCPMonitor.ensure_online(30)`: retry each down server at most once per 30 s. |
| 5 | `server.py` `/swarm` | `"  /swarm fix it"` lost its first letters (sliced the unstripped text). Keywords with a comma (`"test,"`) did not match. | Slice the stripped text. Match words with a regex. |
| 6 | `server.py` docs/retrieval | A system message with list content (images) raised `TypeError` in `_add_docs`. Retrieval skipped silently. | `_append_system_text` handles both shapes. |
| 7 | `server.py` errors | Bad chat request answered 502 (should be 400). Client leaving mid-reply gave a traceback. `BadStatusLine` from llama-swap was not caught. | Mapped to 400 / ignored / 502. |
| 8 | `mcp_monitor.py` | One stdout line that is valid JSON but not an object (`123`, `[]`) killed the reader thread. Every later call then timed out. | Skip non-objects. Never block on a full reply slot. Ignore server-to-client requests. |
| 9 | `mcp_monitor.py` | `tools/list` read only page 1 (spec uses `nextCursor`). A non-object tool entry crashed the handshake. | Read all pages (max 20). Drop bad entries. |
| 10 | `mcp_monitor.py` | Every status check sent `initialize` again. A strict server answered with an error and the monitor then KILLED the healthy server. | Healthy server: refresh `tools/list` only. |
| 11 | `mcp_monitor.py` | Two servers with one name replaced each other silently. | Name gets `-2`, `-3`. |
| 12 | `mcp_chat.py` | A tool with no parameters called with `"arguments": null` failed as invalid. | `null` means `{}`. |
| 13 | `mcp_commander.py` | `read_workspace_file` could read `.git/config` (remote URLs with tokens), `.env`, `*.pem`, `*.key`. Only listing hid `.git`. | Protected-file check in read, verify and list. |
| 14 | `mcp_commander.py` | `settings.json` was readable in clear text, including `upstream_api_key`. | Values of key/token/secret/password fields are masked. |
| 15 | `mcp_commander.py` | Whole file loaded before the size check. Binary files returned garbage. Hashing loaded the whole file. | `stat` first. Refuse NUL bytes. Hash in 1 MB blocks. |
| 16 | `mcp_commander.py` | `git_diff` said "truncated to 12 KB" but kept the LAST 12 KB (the start was lost). Listing cut at 200 without saying so. | Keep the start. `truncated` flag in both. |
| 17 | `mcp_commander.py` | Windows stdio is cp1252: non-ASCII file text broke or garbled the reply. | Force UTF-8 on stdin/stdout. |
| 18 | `mcp_commander.py` | An id-less message other than `notifications/*` got a reply with `"id": null`. `params` not an object gave -32603. Client protocol version ignored. | No reply to notifications. -32602 for bad params. Echo a supported version. |

## Found, NOT changed (your decision)
- `/swarm` prints "Executing in parallel... each agent will execute" but nothing runs. It only prints a plan. The text is misleading.
- If the client sends its own `tools`, and the model calls one of them, the loop answers "Unknown MCP tool" instead of handing the call back. `as_sse` also drops `tool_calls` and `usage`.
- Duplicate-call suppression lasts for the whole request. A model that legitimately re-reads a file it just changed is told "duplicate".
- Dormant `mcp_agent.py` writes into its own folder (`HERE`). Not launched by default. Already in `docs/ATLAS-MCP-AUDIT.md`.
- `mcp_chat.max_tokens` is raised to at least 1024 even if the client asked for less.
