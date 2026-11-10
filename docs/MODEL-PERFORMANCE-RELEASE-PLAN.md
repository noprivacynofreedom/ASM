# Model performance release plan

**Status:** v0.2 coordinated release plan. The current baseline app install comes first. Optimization source edits resume after startup checks. No model-runtime defaults changed.

## Goal

Improve perceived response time and resource use for local inference without trading away task quality or stability. Treat cold model start, warm first-token delay, prompt processing, token generation, and model unload as separate measurements. Do not claim a speed or accuracy gain until the same hardware, model file, prompt set, and runtime build have been compared.

## Current source audit

- Atlas routes local inference through llama-swap at `127.0.0.1:8080` and a Vulkan llama.cpp server.
- The local llama-swap configuration declares one model active at a time, five model aliases, and a 900-second idle TTL. The installed binary reports llama-swap `v270 (a093766)` and llama.cpp `0.9.0-dev` build `12125` (`7d516e25e`). Config validation passed for five models and zero peers. Confirm actual swap behavior before changing this policy.
- The configured primary model is a 35B-A3B MoE GGUF. It asks llama.cpp to offload layers to GPU, keep 28 MoE experts on CPU, use a 32K context, use Q8 KV, run one sequence slot, use Flash Attention, and enable draft MTP. These settings are hypotheses to benchmark, not proven wins.
- The primary GGUF file is 21.71 GB on disk, larger than the config comment's 16 GB VRAM figure. CPU placement and VRAM headroom matter. Measure peak usage rather than assuming full GPU residency.
- A second dense 31B profile uses 44 GPU layers and an 8K context. Compare its startup and quality against the MoE model for tasks that need a stronger dense model.
- The local config comment reports 16 GB VRAM and 31 GB RAM. This session could not read hardware telemetry. Verify these values on the target PC before using them as release facts.
- Atlas has a model benchmark command, but its Ollama path sends `keep_alive: "0"`, which forces unload after its request and cannot measure a warm request. Its OpenAI-compatible path estimates token speed from total wall time, so it mixes model startup, prompt processing, and generation. The fallback also reuses a timer started before the attempted Ollama request, which can contaminate its measurement. Do not use the displayed number as decode tokens per second.
- The active desktop release validation reports source checks passing and NSIS packaging in progress. No Atlas model endpoint was listening when checked, so this pass has no cold-start, warm-start, unload, GPU, or CPU benchmark result.
- All five configured model files exist. The local llama-swap config validator passed; this validates the YAML and declared model list, not model startup or GPU fit.

## Release work map

| Stage | Work | Exit evidence |
| --- | --- | --- |
| 0. Freeze baseline | Record commit, binary hashes, model file hashes, llama-swap and llama.cpp versions, driver, GPU/VRAM, RAM, power mode, settings, and ambient load. Run each case three times after one warm-up. | Baseline CSV and raw logs are saved. |
| 1. Measure | Add separate cold load, ready time, warm TTFT, prompt tokens/sec, generation tokens/sec, total latency, unload time, peak VRAM/RAM, and CPU/GPU utilization. Test one request and two queued requests. | Metrics have definitions, units, sample count, and raw source fields. |
| 2. Tune one variable | Compare GPU/CPU MoE split, context size, KV type, mmap/load mode, draft MTP, flash attention, and idle TTL one at a time. Restore baseline between runs. | A result table reports median and p95 plus quality checks for each candidate. |
| 3. Check model quality | Use a fixed local task set for Atlas coding, tool selection, JSON schema validity, and general responses. Keep prompt, system text, decoding settings, and token limit fixed. Add a public benchmark only when the model/task license and scoring are suitable. | No critical task regresses. Report accuracy and failure examples beside speed. |
| 4. Change design | Add proper startup and unload measurements to the benchmark path. Keep defaults conservative; let profiles expose an explicit memory budget and concurrency policy. Do not refactor the provider interface until measurements show duplicated or blocking lifecycle code. | Tests prove endpoint compatibility, request timeout behavior, model swap correctness, and unload recovery. |
| 5. Release candidate | Run source tests, package build, startup/recovery tests, cold and warm benchmark matrix, idle expiry test, and UI model switch test. Save versioned results and hashes. | No unexplained regressions; rollback settings and previous package are available. |

## Swarm delivery map

| Owner | File scope | Deliverable and handoff |
| --- | --- | --- |
| Fix model loading and chat flow | Root `index.html` and its packaged mirror | Scoped image attachment, voice availability/language, and benchmark result UI. Report source checks before release packaging. |
| Improve model reliability and offloading | `atlas-rust-desktop/src-tauri/src/atlas_node.rs` and isolated tests | Correct timer boundaries and distinguish Ollama server timings from OpenAI whole-request estimates. Report tests and fields before UI labels are finalized. |
| Plan Atlas model loading fixes | `docsearch.py` and isolated retrieval tests | Small retrieval correctness or latency improvement with a repeatable test. Keep `server.py` and UI out of scope. |
| Validate Atlas Chat release build | Build scripts, Tauri package artifacts, installer, and install checks | Wait for source owners, package the integrated files, preserve rollback, and report exact hashes and runtime checks. |
| Research model performance optimizations | This plan and integration review | Keep the shared work map current; compare owner evidence to release gates and record blockers. |

The release owner must package the updated root UI from the bundled runtime resources. A Vite rebuild alone does not copy that file. Install only after the resource hash matches and model benchmark labels match the runtime fields.

Workflow, retrieval, image, and voice work stays scoped to the existing features. Add broader feature work only when a check shows a concrete bug or missing control; do not combine unrelated redesigns with the model performance release.

**Sequence gate:** keep current candidate files frozen through the baseline app install and startup checks. Then resume the scoped model benchmark, workflow, retrieval, image, and voice improvements. Integrate those changes into a later candidate, run each owner’s regression checks, and rebuild only after all source owners report ready.

## Baseline candidate record

- Built: 2026-11-09, isolated Rust target `atlas-rust-desktop/src-tauri/target/isolated-atlas-release`.
- Tauri release build and NSIS package: **passed**. The updated packaged `atlas/index.html` matches the root UI source SHA-256.
- Executable SHA-256: `BCC4D6D61A85D160D2C56667844240DC28271FE3FFB59DFB2C3AC0F051607749`.
- Installer: `atlas-rust-desktop/src-tauri/target/isolated-atlas-release/release/bundle/nsis/Atlas Chat_0.1.1_x64-setup.exe`, 327,963,936 bytes, SHA-256 `46C160BE0BCFF8C1B49BD939CF0579DE2111C44457166F8AC433D6152BBC0D3F`.
- Install and startup verification: **pending** with the release owner. Do not call this candidate installed or runtime-verified yet.
- Model load, first-token, generation, unload, CPU/GPU, and quality measurements: **not run** because no model server was active.

## Benchmark protocol

1. Use the same machine and power mode. Close unrelated GPU jobs. Capture GPU VRAM, system RAM, CPU use, GPU utilization, and temperature before and during each run.
2. For each model profile, record one cold start after verified unload, then three warm requests. Record model-ready time from the request that triggers load until the endpoint is ready. Record API TTFT from request send until first streamed token; if streaming is unavailable, mark TTFT unavailable instead of estimating it.
3. Separate prompt prefill rate from generated-token rate. Preserve server token counts and timings when available. Do not divide generated tokens by whole request wall time and label it generation speed.
4. Test short prompt, long prompt, short answer, and fixed long answer. Keep maximum context and output tokens fixed within each comparison.
5. Test concurrency at 1 and 2. On this 16 GB VRAM target, never assume two large models should stay loaded together. Compare queued requests on one model with two simultaneously loaded models only if VRAM headroom is observed and both processes can be safely supervised.
6. Measure unload start-to-process-exit and resource return after the configured idle TTL. Check that an in-flight request completes and the next request reloads the right model.
7. Report median and p95 across repeated runs. Keep raw CSV and server logs with the release artifact.

## Initial optimization hypotheses

- **Model residency:** a 900-second TTL may avoid repeated cold loads during active work but retain large models during idle. Compare 0, 120, 300, and 900 seconds against observed session gaps and memory pressure. Keep the current value until data supports a change.
- **Spin-down timing:** llama-swap v270 documents `POST /api/models/unload/:model_id`. Use that lifecycle API for repeatable cold-start tests, and time the unload response plus process/resource exit. Do not unload a model while a live request uses it.
- **CPU/GPU split:** GPU placement generally lowers latency only while VRAM fits weights, KV cache, and runtime headroom. Compare the current `--n-cpu-moe` and GPU layer settings with a small sweep. Reject configurations that cause paging, OOM, or unstable token speed.
- **KV cache:** KV demand grows with context length and concurrent sequences. Compare 8K, 16K, and 32K context at one slot before changing parallelism. Compare Q8 KV to the current profile only with quality and kernel compatibility checks.
- **Load mode:** compare mmap and the current load mode on this Windows system using cold start, resident RAM, page faults, and warm decode speed. Do not infer that loading less into RAM is faster from the config comment alone.
- **Speculative decoding:** compare draft MTP on and off using identical prompts. Keep it only if acceptance rate and end-to-end latency improve without quality or reliability loss.
- **Multiple models:** preserve single-active-model swapping as the default until memory telemetry shows safe headroom. If two models are needed at once, use an explicit compatible group and a shared concurrency/resource limit. A longer TTL alone does not guarantee safe simultaneous residency.
- **Quantization and accuracy:** compare candidate GGUF files on the same task set. Perplexity can catch distribution loss, but it does not replace task accuracy, tool-call validity, or human review of representative failures.

## Refactor assessment

The current measurable gap is the benchmark contract, not evidence that the inference provider needs a broad rewrite. First split benchmark results into cold load, warm latency, prefill, decode, unload, and resource fields. Then isolate provider-specific telemetry behind a small adapter while retaining the current OpenAI-compatible request path. Avoid moving the Python compatibility server or changing the desktop lifecycle during this optimization release. Keep one-model swapping until the concurrency experiment demonstrates a safe memory budget.

## Sources

- llama.cpp server options cover continuous batching, Flash Attention, KV cache types, parallel slots, and prompt cache behavior: [server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
- llama.cpp documents how context length and parallel slots affect KV memory, and recommends reducing context or slots before reducing GPU offload: [multi-GPU troubleshooting](https://github.com/ggml-org/llama.cpp/blob/master/docs/multi-gpu.md).
- llama.cpp describes importance matrices for quantization: [imatrix README](https://github.com/ggml-org/llama.cpp/blob/master/tools/imatrix/README.md). Quantization impact depends on model and calibration data; example perplexity deltas are not Atlas accuracy claims.
- llama.cpp describes perplexity as one way to compare quantized model quality: [perplexity tool README](https://github.com/ggml-org/llama.cpp/blob/master/tools/perplexity/README.md).
- llama-swap supports TTL-based unloading and explicit concurrent model groups; its runtime configuration must be checked before changing the local single-model policy: [llama-swap project](https://github.com/mostlygeek/llama-swap), [configuration schema](https://github.com/mostlygeek/llama-swap/blob/main/config-schema.json).
- EleutherAI's harness supports repeatable zero-shot and few-shot task evaluation with task and generation settings: [LM Evaluation Harness](https://github.com/EleutherAI/lm-evaluation-harness).

## Current release decision

**Do not change model runtime defaults yet.** First collect an on-device baseline and correct the benchmark so it separates loading, prompt, generation, and unloading. The running release validation remains the source of build status. Hardware benchmark and packaged Windows runtime status remain open.
