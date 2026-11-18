# Atlas Swarm Framework

This document defines the architecture and handoff contract for Atlas Chat swarms, the unified Swarm Board, state caching, and lightweight summary/archive APIs.

## 1. Unified Swarm Board

Atlas Chat exposes one unified **Swarm Board** across the main chat UI and the Operations / llama-swap view:

- **Swarm Board view (`atlas_botlogs.js`)**: Mounted at `#/atlas-bot-logs` (`#atlas-botlogs`), providing live/problem/archived filtering, debounced search, poll deduplication (`lastJson`), per-worker chip toggles, `Archive` / `Unarchive` actions, and `Open Chat` links.
- **In-chat Swarm Bar & Tree (`index.html`)**: `#swarmBar` (`renderSwarmBar`) and `renderSwarmTree` open the unified Swarm Board via `openBotLogs(run_id)`.
- **Cross-frame `postMessage` bridge**:
  - `atlas:open-swarm-board` (`{ type: "atlas:open-swarm-board", run_id }`): Opens the unified Swarm Board, optionally focused on `run_id`.
  - `atlas:open-chat` (`{ type: "atlas:open-chat", run_id, conversation_id }`): Navigates from a Swarm Board run card back to the matching Atlas Chat conversation.

## 2. State Caching (`_load_state`)

`data.json` can grow to ~2 MB+. To avoid repeated disk reads and JSON re-parsing on every poll or API request, `server.py` uses `_STATE_CACHE` guarded by `_lock`:

- `_load_state()` checks `os.stat(DATA)` (`st_mtime_ns` and `st_size`). When unchanged, it returns the cached parsed dict immediately.
- `_load_state_raw()` returns cached UTF-8 JSON bytes alongside the parsed dict for full `/api/state` responses.
- `_save_state(data)` writes atomically via `data.json.tmp` + `os.replace`, then refreshes `_STATE_CACHE` with the new `mtime_ns`, `size`, `data`, and `raw_bytes`.

### Summary & Archive Endpoints

- `GET /api/state?summary=1`: Returns `bots`, summarized `chats` (`_summarize_chat`, omitting full `messages` arrays), and `"summary": true`.
- `GET /api/conversations?kind=...&archived=...&q=...&limit=...&offset=...`: Filters and paginates conversation summaries (`kind`: `all|swarm|chat`, `archived`: `all|only|exclude`).
- `GET /api/conversations/<id>`: Returns a single full conversation with summary metadata attached.
- `GET /api/ops/swarm/runs?summary=1&category=...&state=...&limit=...&lines=...`: Returns enriched swarm runs (`title`, `summary` worker counts, `worker_summaries`, `archived`) while stripping verbose `lines` and `routes` arrays when `summary=1`.
- `POST /api/conversations/<id>/archive` and `POST /api/ops/swarm/runs/<run_id>/archive`: Persist `archived` boolean state (`{"archived": true|false}`) atomically via `_save_state`.

## 3. Lossless Worker Handoffs

To keep context small, fast, and deterministic:

1. **Reference by ID and path**: Pass `run_id`, `conversation_id`, `task_id`, `trace_id`, file paths, and line ranges instead of pasting full `data.json` snapshots or long raw transcripts.
2. **Use summary endpoints first**: Inspect lists via `/api/conversations` or `/api/ops/swarm/runs?summary=1` (or MCP tools `atlas_list_conversations` and `atlas_swarm_runs`); fetch `/api/conversations/<id>` only for the specific conversation under inspection.
3. **Structured telemetry**: Workers using `AtlasAgent` (`agents/atlas_agent_runtime.py`) should emit concise `event()` records with `task_id` and `trace_id`, maintain heartbeats, and return structured `result` dicts.
4. **Verify before reporting**: Only mark work complete after running relevant checks and reporting exact file paths, symbol names, and observed test results.

## 4. Hyperswarm Modes

`/swarm [mode] <goal>` and `/hyperswarm <goal>` support 3 modes:

- **`hyper`** (default for `/hyperswarm`): Blended hybrid hivemind. Combines free cloud tier APIs (Gemini Flash, Groq 70B, Cerebras, OpenRouter, GitHub Models) + local models + MCP tools.
- **`local`** (`/swarm local <goal>`): 100% offline, air-gapped local models on this PC and LAN peers with zero external cloud calls.
- **`abliterated`** (`/swarm abliterated <goal>`): Uncensored mode using unrestricted model routing and direct objective prompts without refusal filters.
