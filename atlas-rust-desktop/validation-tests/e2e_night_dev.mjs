// Night dev panel in a real browser: opens from the header, keyboard works, the page never scrolls (CLAUDE.md 8),
// the dialog fits the window at 1400x900 and phone width, Esc closes it and focus goes back to the button.
// Run from anywhere:  node atlas-rust-desktop/validation-tests/e2e_night_dev.mjs
// Needs Python 3 and Playwright. Optional: DSF=<display scale, e.g. 1.25>, SHOT=<folder for screenshots>.
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
const data = fs.mkdtempSync(path.join(os.tmpdir(), "atlas-night-"));
fs.writeFileSync(path.join(data, "settings.json"), JSON.stringify({ server_port: APP_PORT, upstream_port: FAKE_PORT, embedding_model: "", mcp_auto_tools: false }));
// Seed what a finished night leaves behind: one package, a backlog, a waiting action and a log.
const hd = path.join(data, "headless-dev"), pkg = path.join(hd, "packages", "20261118-1");
fs.mkdirSync(pkg, { recursive: true });
fs.writeFileSync(path.join(pkg, "meta.json"), JSON.stringify({ id: "20261118-1", item_id: "abc", title: "Add a test: mcp_chat.summarize_args hides secret keys and cuts long values", branch: "atlas-auto/20261118-1",
  commit: "f".repeat(40), base: "e".repeat(40), files: ["atlas-rust-desktop/validation-tests/test_summarize_args.py"], tests_passed: true, verdict: "KEEP", reviewer: "local model (mentor)", risks: [], status: "ready", created: 0 }));
fs.writeFileSync(path.join(pkg, "report.md"), "# Night dev package 20261118-1\n\n## What and why\n\nA new test.\n".repeat(20));
fs.writeFileSync(path.join(pkg, "send-to-claude.md"), "# Task for Claude Code\n");
fs.writeFileSync(path.join(hd, "backlog.json"), JSON.stringify(Array.from({ length: 30 }, (_, i) => ({ id: "i" + i, title: "Backlog item number " + i + " with a long title ".repeat(3), detail: "", source: "docs/PLAN.md:" + i, status: i ? "open" : "review", attempts: 0 }))));
fs.writeFileSync(path.join(hd, "queue.json"), JSON.stringify([{ id: "q1", action: "web_search", tier: "consequential", args: '{"q":"x"}', why: "the plan asked for it", status: "waiting", created: 0 }]));
fs.writeFileSync(path.join(hd, "log.jsonl"), Array.from({ length: 80 }, (_, i) => JSON.stringify({ ts: 1763400000 + i, level: i % 7 ? "info" : "warn", phase: "build", message: "Log line " + i + " ".repeat(5) + "x".repeat(120) })).join("\n") + "\n");
const py = process.platform === "win32" ? "python" : "python3";
const procs = [spawn(py, [path.join(HERE, "fake_llama_swap.py"), String(FAKE_PORT), "8192"], { stdio: "ignore" }),
  spawn(py, ["server.py"], { cwd: APP, env: { ...process.env, ATLAS_DATA_DIR: data, ATLAS_OBSERVABILITY_DB: path.join(data, "o.sqlite3"), ATLAS_DEV_REPO: data }, stdio: "ignore" })];
process.on("exit", () => procs.forEach(p => p.kill()));
for (let i = 0; i < 100; i++) { try { if ((await fetch(`http://127.0.0.1:${APP_PORT}/`)).ok) break; } catch {} await new Promise(r => setTimeout(r, 150)); }
const browser = await chromium.launch();
let bad = 0;
const fail = (msg) => { bad++; console.log("FAIL", msg); };
for (const [w, h] of [[1400, 900], [390, 800]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: Number(process.env.DSF || 1) });
  await page.goto(`http://127.0.0.1:${APP_PORT}/`);
  await page.waitForFunction(() => /NIGHT DEV \/\/ OFF/.test(document.querySelector("#nightBtn")?.textContent || ""));
  await page.focus("#nightBtn");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelector("#nightDlg").open && document.querySelectorAll("#ndPkgs button").length >= 2);
  const r = await page.evaluate(() => { const s = document.scrollingElement, d = document.querySelector("#nightDlg").getBoundingClientRect();
    return { sh: s.scrollHeight, ch: s.clientHeight, sw: s.scrollWidth, cw: s.clientWidth, top: d.top, bottom: d.bottom, left: d.left, right: d.right,
      win: innerHeight, winW: innerWidth, focus: document.activeElement?.id, inner: (() => { const b = document.querySelector("#nightDlg .nd-body"); return b.scrollWidth <= b.clientWidth; })() }; });
  if (r.sh !== r.ch || r.sw > r.cw) fail(`${w}x${h} page scrolls ${JSON.stringify(r)}`);
  if (r.top < 0 || r.bottom > r.win || r.left < 0 || r.right > r.winW) fail(`${w}x${h} dialog leaves the window ${JSON.stringify(r)}`);
  if (!r.inner) fail(`${w}x${h} dialog body scrolls sideways`);
  if (r.focus !== "ndStart") fail(`${w}x${h} focus is on ${r.focus}, expected the Start button`);
  // Keyboard: Tab moves through real controls and the focus ring shows.
  await page.keyboard.press("Tab");
  const ring = await page.evaluate(() => { const a = document.activeElement, cs = getComputedStyle(a); return { id: a.id, tag: a.tagName, outline: cs.outlineStyle + " " + cs.outlineWidth }; });
  if (!/BUTTON|INPUT|PRE|DIV/.test(ring.tag) || ring.outline.startsWith("none")) fail(`${w}x${h} focus ring missing ${JSON.stringify(ring)}`);
  // Report opens inline, Approve marks the package (confirm accepted), nothing else changes.
  await page.click("#ndPkgs button[data-do=report]");
  await page.waitForFunction(() => !document.querySelector("#ndReport").hidden && /What and why/.test(document.querySelector("#ndReport").textContent));
  if (process.env.SHOT) await page.screenshot({ path: `${process.env.SHOT}/night-${w}.png` });
  if (w === 1400) {
    page.once("dialog", d => d.accept());
    await page.click("#ndPkgs button[data-do=approve]");
    await page.waitForFunction(() => /approved/.test(document.querySelector("#ndPkgs").textContent));
  }
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !document.querySelector("#nightDlg").open);
  const back = await page.evaluate(() => document.activeElement?.id);
  if (back !== "nightBtn") fail(`${w}x${h} focus did not return to the button (${back})`);
  console.log(`${w}x${h}`, JSON.stringify(r));
  await page.close();
}
// Reduced motion: the running phase chip must not blink.
const rm = await browser.newPage({ viewport: { width: 1400, height: 900 }, reducedMotion: "reduce" });
await rm.goto(`http://127.0.0.1:${APP_PORT}/`);
const anim = await rm.evaluate(() => { const li = document.createElement("li"); li.dataset.s = "now"; const ol = document.querySelector("#ndPhases"); ol.appendChild(li);
  return getComputedStyle(li).animationName; });
if (anim !== "none") fail(`reduced motion still animates (${anim})`);
await browser.close();
const meta = JSON.parse(fs.readFileSync(path.join(pkg, "meta.json"), "utf8"));
if (meta.status !== "approved") fail("approve did not reach the backend");
console.log(bad ? `NIGHT DEV E2E FAILED (${bad})` : "NIGHT DEV E2E PASSED");
process.exit(bad ? 1 : 0);
