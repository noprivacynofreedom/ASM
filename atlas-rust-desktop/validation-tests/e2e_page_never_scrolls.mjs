// The chat page never scrolls (CLAUDE.md section 8): long chat + swarm bar + approval cards,
// at 1400x900, 1280x720 and phone width. Only #log scrolls. The input box stays inside the window.
// Run from anywhere:  node atlas-rust-desktop/validation-tests/e2e_page_never_scrolls.mjs
// Needs Python 3 and Playwright. Optional: N=<approval cards> (default 3), DSF=<display scale>, SHOT=<dir>.
import { spawn } from "node:child_process";
import fs from "node:fs"; import os from "node:os"; import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require(require.resolve("playwright", { paths: ["/opt/node22/lib/node_modules", "/usr/local/lib/node_modules", "/usr/lib/node_modules"] }))); }
const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.join(HERE, "..", "src-tauri", "resources", "atlas");
const FAKE_PORT = 18421, APP_PORT = 18422;
const data = fs.mkdtempSync(path.join(os.tmpdir(), "atlas-scroll-"));
fs.writeFileSync(path.join(data, "settings.json"), JSON.stringify({ server_port: APP_PORT, upstream_port: FAKE_PORT, embedding_model: "", mcp_auto_tools: false }));
const py = process.platform === "win32" ? "python" : "python3";
const procs = [spawn(py, [path.join(HERE, "fake_llama_swap.py"), String(FAKE_PORT), "8192"], { stdio: "ignore" }),
  spawn(py, ["server.py"], { cwd: APP, env: { ...process.env, ATLAS_DATA_DIR: data, ATLAS_OBSERVABILITY_DB: path.join(data, "o.sqlite3") }, stdio: "ignore" })];
process.on("exit", () => procs.forEach(p => p.kill()));
for (let i = 0; i < 100; i++) { try { if ((await fetch(`http://127.0.0.1:${APP_PORT}/`)).ok) break; } catch {} await new Promise(r => setTimeout(r, 150)); }
const browser = await chromium.launch();
let bad = 0;
for (const [w, h] of [[1400, 900], [1280, 720], [390, 800]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: Number(process.env.DSF || 1) });
  const rows = Array.from({ length: Number(process.env.N || 3) }, (_, i) => ({ id: "a" + i, server: "atlas", tool: "web_search", tier: "consequential", args: "query=" + "x".repeat(300), created: 0, expires: Date.now() / 1000 + 600 }));
  await page.route("**/api/approvals", r => r.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, pending: rows }) }));
  await page.goto(`http://127.0.0.1:${APP_PORT}/`);
  await page.waitForFunction(() => document.querySelector("#hdrModel option[value='assist']"));
  await page.evaluate(() => { if (!chat()) newChat(); });
  await page.evaluate(() => { const c = chat() || newChat(); for (let i = 0; i < 80; i++) c.messages.push({ role: i % 2 ? "assistant" : "user", content: "line ".repeat(60) + i }); renderLog();
    const sb = document.querySelector("#swarmBar"); sb.hidden = false; sb.textContent = "SWARM running ".repeat(20); });
  await page.waitForFunction(() => !document.querySelector("#approvals").hidden);
  await page.evaluate(() => document.querySelector("#log").scrollTop = 1e9);
  const r = await page.evaluate(() => { const s = document.scrollingElement; return { sh: s.scrollHeight, ch: s.clientHeight, body: document.body.scrollHeight, win: innerHeight,
    input: document.querySelector("#input")?.getBoundingClientRect().bottom, sw: s.scrollWidth, cw: s.clientWidth }; });
  const ok = r.sh === r.ch && r.sw <= r.cw && r.input <= r.win;
  if (!ok) bad++;
  console.log(`${w}x${h}`, ok ? "OK" : "SCROLLS", JSON.stringify(r));
  if (process.env.SHOT) await page.screenshot({ path: `${process.env.SHOT}/scroll-${w}.png` });
  await page.close();
}
await browser.close(); console.log(bad ? "PAGE SCROLLS at " + bad + " size(s)" : "E2E PASSED: page never scrolls");
process.exit(bad ? 1 : 0);
