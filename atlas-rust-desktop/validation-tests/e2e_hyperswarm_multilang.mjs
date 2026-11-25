// End-to-end Chromium browser test for Hyperswarm UI + real multi-language project files
// (.py, .js, .ts, .rs, .html, package.json, Cargo.toml + auto-generated run.bat / run.sh).
// Run from repo root: NODE_PATH=/tmp/pw-node/node_modules node atlas-rust-desktop/validation-tests/e2e_hyperswarm_multilang.mjs
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require("playwright")); }
catch { ({ chromium } = require(require.resolve("playwright", { paths: ["/tmp/pw-node/node_modules", "/opt/node22/lib/node_modules", "/usr/local/lib/node_modules", "/usr/lib/node_modules"] }))); }

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.join(HERE, "..", "src-tauri", "resources", "atlas");
const FAKE_PORT = 18481, APP_PORT = 18482;
const data = fs.mkdtempSync(path.join(os.tmpdir(), "atlas-hyperswarm-e2e-"));
const wsDir = path.join(data, "workspace");
fs.mkdirSync(wsDir, { recursive: true });
fs.writeFileSync(path.join(data, "settings.json"), JSON.stringify({
  server_port: APP_PORT, upstream_port: FAKE_PORT, embedding_model: "", mcp_auto_tools: false, workspace_dir: wsDir,
}));

const MULTILANG_REPLY = [
  "Implemented the multi-language project.",
  "",
  "FILE: api/main.py",
  "```python",
  'def status(): return {"ok": True}',
  "```",
  "",
  "FILE: web/app.js",
  "```js",
  'export const APP = "atlas-demo";',
  "```",
  "",
  "FILE: web/types.ts",
  "```ts",
  "export interface Health { ok: boolean; }",
  "```",
  "",
  "FILE: core/Cargo.toml",
  "```toml",
  '[package]\nname = "core"\nversion = "0.1.0"\nedition = "2021"',
  "```",
  "",
  "FILE: core/src/main.rs",
  "```rust",
  'fn main() { println!("atlas-core"); }',
  "```",
  "",
  "FILE: web/index.html",
  "```html",
  "<!doctype html><html><body><h1>Atlas Demo</h1><script>console.log(1)</script></body></html>",
  "```",
].join("\n");

// Fake llama-swap server returning multi-language FILE blocks
const fakeLlm = http.createServer((req, res) => {
  let body = "";
  req.on("data", c => { body += c; });
  req.on("end", () => {
    if (req.url === "/v1/models") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ object: "list", data: [{ id: "assist" }, { id: "coder" }, { id: "mentor" }, { id: "tasks" }] }));
      return;
    }
    if (req.url === "/v1/chat/completions") {
      let parsed = {};
      try { parsed = JSON.parse(body); } catch {}
      if (parsed.stream) {
        res.writeHead(200, { "Content-Type": "text/event-stream; charset=utf-8" });
        const chunk = { id: "c1", object: "chat.completion.chunk", choices: [{ index: 0, delta: { role: "assistant", content: MULTILANG_REPLY }, finish_reason: null }] };
        const end = { id: "c1", object: "chat.completion.chunk", choices: [{ index: 0, delta: {}, finish_reason: "stop" }] };
        res.end(`data: ${JSON.stringify(chunk)}\n\ndata: ${JSON.stringify(end)}\n\ndata: [DONE]\n\n`);
      } else {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ id: "c1", choices: [{ index: 0, message: { role: "assistant", content: MULTILANG_REPLY }, finish_reason: "stop" }] }));
      }
      return;
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end("{}");
  });
});

await new Promise(r => fakeLlm.listen(FAKE_PORT, "127.0.0.1", r));

const py = process.platform === "win32" ? "python" : "python3";
const srv = spawn(py, ["server.py"], {
  cwd: APP,
  env: { ...process.env, ATLAS_DATA_DIR: data, ATLAS_OBSERVABILITY_DB: path.join(data, "o.sqlite3"), ATLAS_CLOUD_LLM: "0" },
  stdio: "ignore",
});
const cleanup = () => { try { srv.kill(); } catch {} try { fakeLlm.close(); } catch {} };
process.on("exit", cleanup);

for (let i = 0; i < 100; i++) {
  try { if ((await fetch(`http://127.0.0.1:${APP_PORT}/`)).ok) break; } catch {}
  await new Promise(r => setTimeout(r, 150));
}

const execPath = ["/usr/bin/chromium", "/usr/bin/google-chrome"].find(p => fs.existsSync(p));
const browser = await chromium.launch(execPath ? { executablePath: execPath } : {});
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const pageErrors = [];
page.on("pageerror", e => pageErrors.push(e.message));

try {
  await page.goto(`http://127.0.0.1:${APP_PORT}/`);
  await page.waitForFunction(() => document.querySelector("#hdrModel option[value='assist']"));

  // 1. Slash command picker: /hyperswarm inserts trailing space and does NOT auto-submit empty
  await page.fill("#input", "/hyper");
  await page.waitForSelector("#slashHints li[data-cmd='/hyperswarm']");
  await page.dispatchEvent("#slashHints li[data-cmd='/hyperswarm']", "mousedown");
  const valAfterPick = await page.inputValue("#input");
  if (valAfterPick !== "/hyperswarm ") throw new Error(`Expected '/hyperswarm ', got ${JSON.stringify(valAfterPick)}`);
  console.log("PASS 1: /hyperswarm slash picker inserts trailing space without auto-submit");

  // 2. Hyperswarm modal (#backgroundDlg) has mode selector (hyper, local, abliterated)
  await page.click("#backgroundBtn");
  await page.waitForSelector("#backgroundDlg[open]");
  const modes = await page.$$eval("#backgroundMode option", opts => opts.map(o => o.value));
  if (modes.join(",") !== "hyper,local,abliterated") throw new Error(`Unexpected modes: ${modes}`);
  await page.selectOption("#backgroundMode", "local");
  await page.fill("#backgroundGoal", "implement a multi-language python js ts rust html app");
  await page.click("#backgroundForm button[value='start']");
  console.log("PASS 2: Hyperswarm modal mode selector works and submits swarm run");

  // 3. Wait for swarm chats to be created and for the compiled project/ folder to land on disk
  await page.waitForFunction(() => (typeof S !== "undefined" && S.chats || []).some(c => c.swarmRun), { timeout: 15000 });
  const runId = await page.evaluate(() => S.chats.find(c => c.swarmRun).swarmRun);
  const projDir = path.join(wsDir, "swarm-output", runId, "project");
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline && !fs.existsSync(path.join(projDir, ".atlas-project.json"))) {
    await new Promise(r => setTimeout(r, 150));
  }
  const expectedFiles = [
    "api/main.py", "web/app.js", "web/types.ts", "core/Cargo.toml",
    "core/src/main.rs", "web/index.html", "run.sh", "run.bat", ".atlas-project.json",
  ];
  for (const rel of expectedFiles) {
    if (!fs.existsSync(path.join(projDir, rel))) throw new Error(`Missing compiled project file: ${rel}`);
  }
  console.log(`PASS 3: Compiled project/ folder written on disk (${expectedFiles.length} real files + run scripts)`);

  // 4. Switch to SWARM tab, open swarm chat, verify mode badge + FILES button + file preview
  await page.click("#tabSwarm");
  await page.waitForSelector("#chats .swarm-run button.open");
  await page.click("#chats .swarm-run button.open");
  await page.waitForSelector("#swarmBar:not([hidden]) [data-swarmfiles]");
  const barText = await page.textContent("#swarmBar");
  if (!barText.includes("LOCAL")) throw new Error(`Expected LOCAL mode pill in #swarmBar, got: ${barText}`);
  await page.click("#swarmBar [data-swarmfiles]");
  await page.waitForSelector("#swarmFilesDlg[open] #swarmFilesList button");
  const listed = await page.$$eval("#swarmFilesList button", bs => bs.map(b => b.textContent));
  if (!listed.some(t => t.includes("project/core/src/main.rs")) || !listed.some(t => t.includes("project/web/types.ts"))) {
    throw new Error(`Expected project .rs and .ts files in FILES modal, got: ${JSON.stringify(listed)}`);
  }
  // Click core/src/main.rs and verify preview shows real Rust code
  const rsBtn = page.locator("#swarmFilesList button", { hasText: "project/core/src/main.rs" }).first();
  await rsBtn.click();
  await page.waitForFunction(() => document.querySelector("#swarmFilesPreview")?.textContent?.includes("atlas-core"));
  await page.click("#swarmFilesDlg button[value='cancel']");
  console.log("PASS 4: #swarmBar mode pill + FILES viewer displays real .py/.js/.ts/.rs/.html files");

  // 5. Page never scrolls & zero page errors
  const dims = await page.evaluate(() => ({ sh: document.scrollingElement.scrollHeight, ch: document.scrollingElement.clientHeight }));
  if (dims.sh !== dims.ch) throw new Error(`Page scrolled: ${JSON.stringify(dims)}`);
  if (pageErrors.length) throw new Error(`Page errors: ${pageErrors.join("; ")}`);
  console.log("PASS 5: Page never scrolls and zero console pageerrors");
  console.log("E2E PASSED: Hyperswarm UI + real multi-language project files");
} finally {
  await browser.close();
  cleanup();
}
process.exit(0);
