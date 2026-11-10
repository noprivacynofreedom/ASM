# Atlas Swarm Manager delivery plan

**Status:** baseline installer verification in progress. Feature source edits and folder rename wait until the current app install and startup checks pass.

## History sweep

I checked 38 recent Codex history entries and 114 ChatGPT history records, filtered 16 Atlas-related conversations, and reviewed recent turns in those threads. I found overlapping work, so this plan treats old requests as backlog evidence and current owner reports as implementation evidence. Unrelated Nyx, Raspberry Pi, and general chats stay out of this Atlas plan.

## Feature inventory

| Request | Current evidence | Next acceptance check |
| --- | --- | --- |
| Reliable current-app installer and in-place update | A 0.1.1 NSIS candidate exists. Release checks caught a benchmark regression before install. The reliability owner fixed the mock test; release owner is rebuilding and will install after checks. | Verify installer hash, install over current app, retain user data, launch app, confirm services and MCP start, close app, and confirm only owned services stop. |
| Model discovery, loading, switching, CPU/GPU split, KV cache, TTL, multiple models, speed and quality | llama-swap v270 and llama.cpp `0.9.0-dev`; five valid profiles. Current primary profile uses Q8 KV, 32K context, one slot, Vulkan offload and CPU MoE. Model benchmark timing patch is in the candidate. No on-device inference benchmark exists yet. | Measure cold load, warm time-to-first-token, prompt and decode rates, unload, VRAM/RAM, CPU/GPU load, and task-quality results. Compare one setting at a time. |
| Chat UI and model controls | Current UI stacks Context, Plugins and MCP panels, highlights the active panel, loads status at startup, and hides test controls by default. Source checks passed. | Verify panels, empty/error states, model selection, chat send/retry, and recovery in installed WebView. |
| Workflow and safe parallel agents | `dev_cycle.py` exists; prior project review reports Team Run currently executes sequentially. Older requests describe isolated workspaces, dependency-aware scheduling, per-agent progress/tests/review, and explicit approval before integration. | Run dependent and independent tasks; verify workspace isolation, dependency order, cancellation, failure recovery, test evidence, and no direct writes to the live tree. |
| Knowledge Library and retrieval | `server.py` and `knowledge_engine.py` provide import, PDF extraction with optional OCR, semantic retrieval with lexical fallback, distillation, graph and student packs. `docsearch.py` provides a separate simple keyword search. | Import text and PDF, test scanned-PDF OCR when installed, retrieve a known fact with source attribution, verify lexical fallback with inference offline, and test malformed/oversized input. |
| Image input and detection | Chat UI has image attachments. Current route still needs a verified vision-capable model path and a clear unsupported-model state. | Send one image to a vision model and a text-only model. Confirm the first receives the image and the second shows a useful error without losing the text prompt. |
| Voice input settings | Browser speech dictation exists, but current code uses the browser default language. | Select and persist a language; test allowed, denied, unavailable, and empty-recognition states. Confirm the transcript enters the intended chat only. |
| Bot activity companion | New request: a compact, pet-like Atlas companion that helps track every bot action. Existing Operations data has bot/chat/queue state and MCP audit records, but event coverage must be confirmed. | Show real time-stamped action, bot, status, and outcome events. Check queue, model, tool, failure, retry, and completion events. Label missing data instead of inventing status. |
| MCP and plugin integration | Atlas Chat already has an MCP monitor, tool loop, audit recorder, and internal `atlas-commander`. History also requests separate read-only Atlas and Atlas Chat Bridge connections, scoped roots, and no write/delete/arbitrary command tools. | Verify each adapter exposes only its approved roots and read tools; reject writes, deletes, and commands; test audit states and exact path errors end to end. |
| Node and Operations | Tauri UI has hardware telemetry, model benchmark, consent/policy controls, network status and contribution ledger. Existing lifecycle policy separates local node participation from remote execution. | Verify live telemetry, consent changes, owned-process cleanup, model list, audit view, and accurate unavailable states. |
| Product and project rename | Requested project folder `atlas-chat` → `atlas-swarm-manager` and visible app name `Atlas Swarm Manager`. The Codex project label already reads “ASM - ATLAS SWARM MANAGER”; no project-rename API is available in the connected app tools. Tauri `productName` also controls Windows install directory, Start Menu folder, and registry key, so keeping the app identifier alone does not preserve the old install destination. | Update active source paths, launch/build/install scripts, package/product labels, window titles and help text. Keep `dev.atlas.chat` to preserve the app data path. Test the old-to-new installer upgrade path and user-data access before release. Search again, build, upgrade, and verify existing app data remains available. |

## Owners and file boundaries

| Owner | Scope | Order |
| --- | --- | --- |
| Validate Atlas Chat release build | Current installer, install, startup, packaged-resource checks | First. Do not add source changes to this candidate after its final regression run. |
| Improve model reliability and offloading | `atlas_node.rs` benchmark contract and subsequent runtime measurements | After baseline install. The current timing patch is in the candidate; verify its test before install. |
| Plan Atlas model loading fixes | `docsearch.py` and retrieval tests | After baseline install. Keep `server.py` and UI outside this scope. |
| Fix model loading and chat flow | `index.html`, packaged UI mirror, `App.tsx`, Knowledge Library UI and image/voice controls | After baseline install. Own visible activity companion UI; use real event sources. |
| Research model performance optimizations | `docsearch.py`, `dev_cycle.py`, and their focused tests after baseline install | Owns retrieval and workflow implementation; keep `server.py` and UI outside this scope. |
| Coordinate MCP tool development | `F:\APP-DEV\mcp-project-bridge` only | Keep Bridge changes outside Atlas release source until separately reviewed and integrated. |
| Research model performance optimizations | Rename inventory, release plan, integration checks | Keep the map current and review owner evidence. |

## Rename sequence

1. Finish and verify the current 0.1.1 baseline install first.
2. Freeze the new project path and visible name: `F:\APP-DEV\projects\atlas-swarm-manager` and `Atlas Swarm Manager`.
3. Update first-party source, mirrored runtime, scripts, docs, icons/title surfaces, and release paths. Keep historical backups, generated logs, and old patch archives unchanged as audit records.
4. Keep the Tauri identifier `dev.atlas.chat` for the first rename release so user-data location remains stable. Test how the changed `productName` affects the existing install directory, Start Menu entry, and registry key before upgrading.
5. Rename the project folder only after every active source owner has finished. Update all path references, then validate the Codex project entry and launcher path.
6. Run static reference search, unit/regression checks, production build, installer upgrade, and installed app end-to-end tests.

## Integration gates

1. Baseline installer passes hash verification, install, launch, service health, user-data preservation, and shutdown checks.
2. Owners complete their scoped edits and tests. Any schema change goes to the UI owner before labels or controls change.
3. Integrate workflow, retrieval, image, voice and activity events with no file-owner collisions.
4. Run the full test suite, including MCP and queue tests, Rust tests, frontend build, retrieval tests, and workflow tests.
5. Run installed end-to-end checks for every row above. Record actual model benchmarks and quality results; no speed or accuracy gain is claimed without a measured comparison.
6. Apply the project and product rename, build the renamed installer, upgrade in place, verify data and startup, then report hashes, test results, and unresolved gaps.

## Known limits

- No model server was running during the source audit. Model load, unload, GPU/CPU use and quality measurements are still missing.
- The Codex app tools expose no project-path rename action. The local directory can be renamed after all active chats release it, but the Codex project registration may need a user-side path refresh.
- The current installer is still in baseline verification. Do not rename its active root path before the release owner finishes install and startup checks.
