ATLAS DESKTOP — HYBRID RUST TEST BUILD + KNOWLEDGE ENGINE
=========================================================

This is the upgrade to the installed Atlas Rust Test Build. Rust/Tauri owns the
Windows desktop window, lifecycle, health checks, CPU/RAM telemetry and owned
child-process shutdown. The existing Python compatibility backend remains the
working model orchestration + MCP host while the native Rust service migration
continues. This is intentional: it keeps the existing Atlas features usable.

WHAT IS NOW IN THE KNOWLEDGE ENGINE
----------------------------------
1. SOURCE LIBRARY
   - Markdown, TXT, CSV, JSON, YAML, Python, SQL, LOG, EPUB and PDF imports.
   - Originals and extracted text remain local under .atlas/knowledge.
   - CSVs receive deterministic schema / sample profiling before teacher study.
   - Text PDFs use PyMuPDF or pypdf. Scanned PDFs use PyMuPDF + Tesseract OCR.

2. TEACHER / DISTILLER
   - Select a larger local teacher model in the Knowledge Library.
   - Every selected source is chunked and processed; the previous 120,000
     aggregate-character truncation has been removed.
   - Hierarchical map/reduce consolidates large source collections.
   - Distilled capsules preserve source IDs, source names, limitations, concepts,
     glossary, study questions and structured concept relationships.
   - A 50 MB aggregate distillation safety limit remains to prevent accidental
     unbounded runs. Import limit remains 5 MB per source.

3. EMBEDDING INDEX + RETRIEVAL
   - Default local embedding backend: fastembed BAAI/bge-small-en-v1.5 (CPU).
   - The model is downloaded on first setup/index build; allow internet for that
     first download. It is then cached by FastEmbed on the machine.
   - Optional alternative: set settings.json embedding_model to a llama-swap
     model alias that implements OpenAI-compatible POST /v1/embeddings.
   - If embeddings are unavailable, Atlas explicitly falls back to lexical search;
     it does not pretend that lexical retrieval is vector semantic search.
   - Search is available in the Knowledge Library UI and relevant retrieved
     chunks are injected into normal chat with source titles/provenance.
   - Rebuild the index after changing the embedding model or source corpus.

4. KNOWLEDGE GRAPH
   - The teacher is asked for structured concepts, typed relationships and
     grounded question/answer examples for student training.
   - Atlas persists them with source provenance and exposes an SVG graph view/API.
   - EXPORT STUDENT PACK creates a ZIP with Markdown/JSON knowledge, graph JSON,
     manifest and training.jsonl for retrieval or a later fine-tuning pipeline.
   - This creates teacher-generated training material; it does NOT update model
     weights or claim to fine-tune a student model. Actual weight training is a
     separate operation and must be run with a compatible training stack.

5. MCP / ATOMIC CHATS / DEVELOPMENT CYCLE
   - Existing live MCP chat tool loop, MCP audit, Atomic Chats and Development
     Cycle remain in the compatibility backend. No MCP server configuration,
     chat data, settings, model files or Git metadata is reset by this upgrade.

INSTALL THE UPGRADE
-------------------
Extract this package. Run in PowerShell:

  Unblock-File .\Update-Atlas-Rust-Knowledge.ps1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Update-Atlas-Rust-Knowledge.ps1 -Project "<project folder>"

The updater expects the exact known Rust Test Build snapshot that was installed
in the previous step. It backs up managed files and stops if index.html/server.py
have changed unexpectedly. It does not overwrite data.json, settings.json,
.atlas/knowledge, .webview, exports, models or Git metadata.

INSTALL OPTIONAL KNOWLEDGE DEPENDENCIES
---------------------------------------
Run:

  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup-Atlas-Knowledge.ps1

This installs FastEmbed, PyMuPDF, pypdf, Pillow and pytesseract into Python 3.
Scanned-PDF OCR also requires the Tesseract OCR application installed on
Windows and available on PATH. OCR is bounded to the first 100 pages per PDF.
The first FastEmbed model download needs internet; subsequent indexing is local.

RUST BUILD
----------
The previous direct script command can be blocked by PowerShell policy. Use the
included CMD wrapper instead (it launches a child PowerShell with process-scoped
ExecutionPolicy Bypass):

  .\Build-Atlas-Rust-Test.cmd

Or development mode:

  .\Build-Atlas-Rust-Test.cmd -Dev

Prerequisites: Node.js LTS, Rust stable via rustup, Visual Studio 2022 Build
Tools with Desktop development with C++, and WebView2 Runtime.

The small desktop/index.html is only the Tauri/Vite React bootstrap. Opening it
by double-click is not the way to run Atlas; it now displays an explanation if
opened directly. The actual Atlas web UI is the project-root index.html. The
generated desktop shell opens that UI served locally at 127.0.0.1:8090. It supervises only the child processes it starts; it does not
use global taskkill commands. Python continues to own MCP stdio and model
orchestration in this hybrid migration stage.

CONFIGURE EMBEDDING MODEL (OPTIONAL)
------------------------------------
The default is:
  "embedding_model": "fastembed:BAAI/bge-small-en-v1.5"

To use llama-swap embeddings instead, set that key in settings.json to the
exact model alias that supports /v1/embeddings. Restart Atlas, then use BUILD /
REBUILD KNOWLEDGE INDEX in the Knowledge Library. If the endpoint is not
supported, Atlas reports lexical_fallback and continues to work.

VALIDATION IN THIS BUILD ENVIRONMENT
------------------------------------
- 16 Python tests passed, including >120k character distillation, embedding
  adapter/vector ranking and student knowledge-pack export coverage.
- Python compilation passed.
- Both inline JavaScript blocks passed node --check.
- MCP stdio initialize/discovery/call/independent verification tests passed.
- HTTP smoke: import, reindex, search and graph routes passed in lexical fallback.
- Rust/Cargo Windows executable build was NOT run here: Rust toolchain is not
  installed in this build environment. Windows GPU/model runtime also remains
  to be verified on the user's PC.


CHAT QUEUE
-----------
You can submit messages while Atlas is generating. They are added to OUTGOING
QUEUE and are processed sequentially after the current response completes.
Each queued item captures its target chat, bot and attachments. The queue is
persisted in data.json, limited to 20 messages, supports removal/clear, and can
be manually resumed after an interrupted session.

RUST BUILD ERROR: link.exe NOT FOUND
------------------------------------
Your log shows the frontend build succeeded. Cargo then failed because the
Microsoft MSVC linker was not available in PATH. This is a Windows C++ toolchain
prerequisite, not an Atlas Rust source error.

Install Visual Studio 2022 Build Tools and select:
- Desktop development with C++
- MSVC v143 x64/x86 build tools
- Windows 10 or Windows 11 SDK

Then rerun Build-Atlas-Rust-Test.cmd. It attempts to load the Visual Studio
developer environment automatically using vswhere. If discovery fails, open
"x64 Native Tools Command Prompt for VS 2022" and run the .cmd from there.

The npm allow-scripts warning for esbuild is separate from the linker failure.
The log reports zero npm vulnerabilities; do not blindly approve install scripts.
