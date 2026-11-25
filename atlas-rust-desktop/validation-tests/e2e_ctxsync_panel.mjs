// The SYNC // panel (ctxsync): keyboard open, add a note, Escape closes, page never scrolls, fits at phone width.
// Run from anywhere:  node atlas-rust-desktop/validation-tests/e2e_ctxsync_panel.mjs
// Needs Python 3 and Playwright. Optional: DSF=<display scale> (default 1.25, like Windows 125%).
import { spawn } from "node:child_process";
import fs from "node:fs"; import os from "node:os"; import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require(require.resolve("playwright", { paths: ["/opt/node22/lib/node_modules", "/usr/local/lib/node_modules", "/usr/lib/node_modules"] }))); }
const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.join(HERE, "..", "src-tauri", "resources", "atlas");
const FAKE_PORT = 18431, APP_PORT = 18432;
const data = fs.mkdtempSync(path.join(os.tmpdir(), "atlas-ctxsync-"));  // never the real data folder
fs.writeFileSync(path.join(data, "settings.json"), JSON.stringify({ server_port: APP_PORT, upstream_port: FAKE_PORT, embedding_model: "", mcp_auto_tools: false }));
const py = process.platform === "win32" ? "python" : "python3";
const procs = [spawn(py, [path.join(HERE, "fake_llama_swap.py"), String(FAKE_PORT), "8192"], { stdio: "ignore" }),
  spawn(py, ["server.py"], { cwd: APP, env: { ...process.env, ATLAS_DATA_DIR: data, ATLAS_OBSERVABILITY_DB: path.join(data, "o.sqlite3") }, stdio: "ignore" })];
process.on("exit", () => procs.forEach(p => p.kill()));
for (let i = 0; i < 100; i++) { try { if ((await fetch(`http://127.0.0.1:${APP_PORT}/`)).ok) break; } catch {} await new Promise(r => setTimeout(r, 150)); }
const browser = await chromium.launch();
let bad = 0;
const check = (name, ok, info = "") => { if (!ok) bad++; console.log(`  ${ok ? "OK  " : "FAIL"} ${name} ${info}`); };
for (const [w, h] of [[1400, 900], [390, 800]]) {
  console.log(`${w}x${h}`);
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: Number(process.env.DSF || 1.25), reducedMotion: "reduce" });
  await page.goto(`http://127.0.0.1:${APP_PORT}/`);
  await page.waitForFunction(() => document.querySelector("#hdrModel option[value='assist']"));
  await page.focus("#syncBtn");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelector("#syncPanel").classList.contains("open"));
  const focused = await page.waitForFunction(() => document.activeElement.id === "syncText", null, { timeout: 2000 }).then(() => true, () => false);
  check("Enter opens the panel, focus in the note box", focused);
  await page.waitForFunction(() => /^SYNC \/\/ \d+$/.test(document.querySelector("#syncBtn").textContent));
  const text = `cloud check ${w}`;
  await page.keyboard.type(text);
  await page.keyboard.press("Enter");
  await page.waitForFunction(t => document.querySelector("#syncList").textContent.includes(t), text);
  check("note saved and listed", true);
  const r = await page.evaluate(() => { const s = document.scrollingElement, p = document.querySelector("#syncPanel").getBoundingClientRect();
    return { sh: s.scrollHeight, ch: s.clientHeight, sw: s.scrollWidth, cw: s.clientWidth, left: Math.round(p.left), right: Math.round(p.right), bottom: Math.round(p.bottom), win: innerHeight, vw: innerWidth }; });
  check("page does not scroll", r.sh === r.ch && r.sw <= r.cw, JSON.stringify(r));
  check("panel fits in the window", r.left >= 0 && r.right <= r.vw && r.bottom <= r.win);
  const outline = await page.evaluate(() => { const b = document.querySelector("#syncPanel button[type=submit]"); b.focus(); return getComputedStyle(b).outlineStyle; });
  check("ADD button has a visible focus outline", outline !== "none", outline);
  await page.keyboard.press("Escape");
  check("Escape closes, focus back on SYNC", await page.evaluate(() => !document.querySelector("#syncPanel").classList.contains("open") && document.activeElement.id === "syncBtn"));
  if (process.env.SHOT) await page.screenshot({ path: `${process.env.SHOT}/ctxsync-${w}.png` });
  await page.close();
}
const log = fs.readFileSync(path.join(data, ".atlas", "ctxsync", "default", "log.jsonl"), "utf8").trim().split("\n");
check("log.jsonl holds both notes", log.length === 2, `${log.length} lines`);
await browser.close(); console.log(bad ? `E2E FAILED: ${bad} check(s)` : "E2E PASSED: ctxsync panel");
process.exit(bad ? 1 : 0);
