// Clicks through the features from Google (94ac4f5..8cac3f7) and Codex (5b6bdf1..0ff738f) in a real browser:
// themes, Test Suite Kanban, /swarm help (hyperswarm modes), swarm run + status bar, Swarm Board,
// Run in background, run details (execution panel). Real server.py + index.html, fake llama-swap.
// Run from anywhere:  node atlas-rust-desktop/validation-tests/e2e_google_codex_features.mjs
// Needs Python 3 and Playwright. Optional: SHOT=<folder for screenshots>.
import { spawn } from "node:child_process";
import fs from "node:fs"; import os from "node:os"; import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require(require.resolve("playwright", { paths: ["/opt/node22/lib/node_modules", "/usr/local/lib/node_modules", "/usr/lib/node_modules"] }))); }
const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.join(HERE, "..", "src-tauri", "resources", "atlas");
const FAKE_PORT = 18451, APP_PORT = 18452, URL = `http://127.0.0.1:${APP_PORT}`;
const data = fs.mkdtempSync(path.join(os.tmpdir(), "atlas-feat-"));
fs.writeFileSync(path.join(data, "settings.json"), JSON.stringify({ server_port: APP_PORT, upstream_port: FAKE_PORT, embedding_model: "", mcp_auto_tools: false }));
const py = process.platform === "win32" ? "python" : "python3";
const procs = [spawn(py, [path.join(HERE, "fake_llama_swap.py"), String(FAKE_PORT), "8192"], { stdio: "ignore" }),
  spawn(py, ["server.py"], { cwd: APP, env: { ...process.env, ATLAS_DATA_DIR: data, ATLAS_OBSERVABILITY_DB: path.join(data, "o.sqlite3"), ATLAS_CLOUD_DISABLED: "1" }, stdio: ["ignore", "ignore", "inherit"] })];
process.on("exit", () => procs.forEach(p => { try { p.kill(); } catch {} }));
for (let i = 0; i < 100; i++) { try { if ((await fetch(URL + "/")).ok) break; } catch {} await new Promise(r => setTimeout(r, 150)); }
const shots = process.env.SHOT || "";
let passed = 0; const ok = name => { passed++; console.log("ok -", name); };
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("dialog", d => d.accept());
  await page.goto(URL + "/");
  await page.waitForFunction(() => document.querySelector("#hdrModel option[value='assist']"));
  await page.evaluate(() => { if (!chat()) newChat(); });

  // 1. Themes: DedSec sets data-theme and changes colours; the choice survives a reload.
  const bg = () => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--bg").trim());
  const optikBg = await bg();
  await page.click("#usageBtn");  // the UI THEME select lives in the usage panel
  await page.selectOption("#uiThemeSelect", "dedsec");
  assert.equal(await page.getAttribute("html", "data-theme"), "dedsec");
  assert.notEqual(await bg(), optikBg, "DedSec changes --bg");
  await page.reload(); await page.waitForFunction(() => document.querySelector("#hdrModel option[value='assist']"));
  assert.equal(await page.getAttribute("html", "data-theme"), "dedsec", "theme kept after reload");
  await page.click("#usageBtn");
  await page.selectOption("#uiThemeSelect", "optik");
  assert.equal(await page.getAttribute("html", "data-theme"), null);
  await page.click("#usageClose");
  ok("themes: Optik / DedSec switch, change colours, survive reload");

  // 2. Test Suite Kanban: page loads, add a feature, it shows in its column, tick and move it.
  const ts = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const tsErrors = []; ts.on("pageerror", e => tsErrors.push(e.message)); ts.on("dialog", d => d.accept());
  await ts.goto(URL + "/test-suite");
  await ts.waitForFunction(() => !/Loading/.test(document.querySelector("#statusLine").textContent));
  await ts.click("#addFeatureBtn");
  await ts.fill("#featTitle", "E2E feature");
  await ts.fill("#featTicks", "first tick\nsecond tick");
  await ts.selectOption("#featStatus", "queued");
  await ts.locator("#addForm button[value='ok'], #addForm button[type='submit']").last().click();
  await ts.waitForFunction(() => /E2E feature/.test(document.querySelector("#col-queued").textContent), null, { timeout: 5000 });
  assert.equal(await ts.textContent("#count-queued"), "1");
  await ts.locator("#col-queued input[type=checkbox]").first().check();
  await ts.waitForFunction(() => document.querySelector("#col-queued input[type=checkbox]")?.checked, null, { timeout: 5000 });
  await ts.locator("#col-queued select.status-select").first().selectOption("passed");
  await ts.waitForFunction(() => /E2E feature/.test(document.querySelector("#col-passed").textContent), null, { timeout: 5000 });
  const saved = await (await fetch(URL + "/api/test-suite")).json();
  assert.ok(JSON.stringify(saved).includes("E2E feature"), "feature saved on the server");
  if (shots) await ts.screenshot({ path: path.join(shots, "test-suite.png") });
  assert.deepEqual(tsErrors, [], "test suite page errors: " + tsErrors.join("; "));
  await ts.close();
  ok("Test Suite Kanban: add, tick, move column, saved on the server");

  const send = async (text) => {
    const n = await page.evaluate(() => (chat() || newChat()).messages.length);
    await page.fill("#input", text); await page.press("#input", "Enter");
    await page.waitForFunction(n => chat().messages.length >= n + 2 && !ctrl, n, { timeout: 20000 });
    return page.evaluate(() => chat().messages.at(-1).content);
  };

  // 3. Hyperswarm modes: /swarm help lists hyper, local and abliterated.
  const help = await send("/swarm help");
  for (const m of ["hyper", "local", "abliterated"]) assert.match(help, new RegExp(m), "help names mode " + m);
  ok("/swarm help lists the hyper, local and abliterated modes");

  // 4. Swarm run in local mode: run starts, swarm status bar shows a health state, swarm tab lists the run.
  const started = await send("/swarm local write a function and test it");
  assert.match(started, /Swarm Started \[Local/);
  await page.waitForFunction(() => S.chats.some(c => c.swarmRun), null, { timeout: 15000 });
  await page.locator("#chats li.swarm-run button.open").first().click();  // the swarm tab opens by itself
  await page.waitForFunction(() => { const b = document.querySelector("#swarmBar"); return b && !b.hidden && b.dataset.health; }, null, { timeout: 15000 });
  const health = await page.getAttribute("#swarmBar", "data-health");
  assert.ok(["running", "warn", "bad", "done"].includes(health), "swarm bar health " + health);
  ok(`swarm run starts in local mode; status bar shows health "${health}"`);

  // 4b. Swarm workspace tools: the run's saved answers are listed and readable (what atlas_swarm_files calls).
  const runId = await page.evaluate(() => chat().swarmRun);
  let files = [];
  for (let i = 0; i < 80 && !files.some(f => f.path.endsWith(".md")); i++) {
    files = (await (await fetch(`${URL}/api/ops/swarm/runs/${runId}/files`)).json()).files || [];
    if (!files.length) await new Promise(r => setTimeout(r, 250));
  }
  const md = files.find(f => f.path.endsWith(".md"));
  assert.ok(md, "swarm run saved an answer file: " + JSON.stringify(files));
  const one = await (await fetch(`${URL}/api/ops/swarm/runs/${runId}/files?path=${encodeURIComponent(md.path)}`)).json();
  assert.ok(one.ok && one.text.length > 0, "answer file readable");
  ok(`swarm files listed and readable (${files.length} files, e.g. "${md.path}")`);

  // 4c. A second /swarm, typed inside the first run's Lead chat, must be its own run in its own atomic group,
  // started from a fresh chat (the 2026-11-18 bug: every run inherited one atomicGroupId and piled together).
  await page.locator("#chats li.swarm-run button.open").first().click();  // open a chat that belongs to run 1
  await page.waitForFunction(r1 => chat() && chat().swarmRun === r1, runId, { timeout: 5000 });
  const insideId = await page.evaluate(() => chat().id);
  await send("/swarm local a second unrelated goal");
  await page.waitForFunction(r1 => S.chats.some(c => c.swarmRun && c.swarmRun !== r1), runId, { timeout: 15000 });
  const groups = await page.evaluate(({ r1, insideId }) => {
    const run2 = [...new Set(S.chats.map(c => c.swarmRun).filter(x => x && x !== r1))][0];
    const g = run => [...new Set(S.chats.filter(c => c.swarmRun === run).map(c => c.atomicGroupId))];
    const origin2 = S.chats.find(c => c.swarmRun === run2)?.swarmOrigin;
    return { run2, g1: g(r1), g2: g(run2), origin2, originIsSwarm: !!S.chats.find(c => c.id === origin2)?.swarmRun, insideId };
  }, { r1: runId, insideId });
  assert.ok(groups.run2, "a second run was created");
  assert.deepEqual(groups.g1, [runId], "run 1's chats stay in run 1's own group");
  assert.deepEqual(groups.g2, [groups.run2], "run 2's chats are in run 2's own group");
  assert.notEqual(groups.origin2, groups.insideId, "run 2 did not nest under the run 1 chat it was typed in");
  assert.equal(groups.originIsSwarm, false, "run 2 started from a fresh normal chat");
  ok("second /swarm starts a fresh run in its own atomic group, not nested under the first");

  // 5. Swarm Board opens from the swarm bar. The board itself is atlas_botlogs.js inside the real llama-swap UI
  // (hw_proxy :8091), which the fake llama-swap does not serve, so check the Operations page and the iframe target.
  await page.locator("#chats li.swarm-run button.open").first().click();  // open a swarm run so the bar shows
  await page.waitForFunction(() => chat() && chat().swarmRun, null, { timeout: 5000 });
  const run = await page.evaluate(() => chat().swarmRun);
  await page.click("#swarmBar [data-botlogs]");
  await page.waitForFunction(r => (document.querySelector("#llama-iframe")?.src || "").includes("#/atlas-bot-logs?run=" + r), run, { timeout: 5000 });
  await page.click("#opsBackToChat");
  await page.waitForFunction(() => document.querySelector("main").offsetParent !== null);
  ok("SWARM BOARD opens Operations with the board for this run; back to chat works");

  // 6. Run in background: the dialog starts a /swarm run.
  await page.evaluate(() => { newChat(); });
  const runsBefore = await page.evaluate(() => new Set(S.chats.map(c => c.swarmRun).filter(Boolean)).size);
  await page.click("#backgroundBtn");
  await page.fill("#backgroundGoal", "check the queue and report");
  await page.locator("#backgroundForm button[value='start']").click();
  await page.waitForFunction(n => new Set(S.chats.map(c => c.swarmRun).filter(Boolean)).size > n, runsBefore, { timeout: 20000 });
  ok("Run in background starts a new swarm run");

  // 7. Run details: the execution panel opens and lists saved actions.
  // Opened at once on purpose: the new chat may not be saved yet (404). That must not show as an error.
  await page.evaluate(() => toggleExecutionPanel(true));
  await page.waitForFunction(() => !document.querySelector("#executionPanel").hidden);
  await page.waitForFunction(() => /history|STEP|TOOL|TASK/i.test(document.querySelector("#executionPanel").textContent), null, { timeout: 5000 });
  assert.doesNotMatch(await page.textContent("#executionPanel"), /API error|Error loading/, "run details show an error");
  await page.waitForTimeout(800); await page.click("#executionRefresh");  // after the save: real history, still no error
  await page.waitForTimeout(800);
  assert.doesNotMatch(await page.textContent("#executionPanel"), /API error|Error loading/, "run details show an error after refresh");
  const tallest = await page.evaluate(() => Math.max(0, ...[...document.querySelectorAll("#executionLog .exec-card")].map(c => c.getBoundingClientRect().height)));
  assert.ok(tallest > 0 && tallest < 120, "closed action cards stay one row high, not stretched: " + tallest);
  if (shots) await page.screenshot({ path: path.join(shots, "run-details.png") });
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => document.querySelector("#executionPanel").hidden, null, { timeout: 3000 });
  ok("run details panel opens with content and closes on Escape");

  const s = await page.evaluate(() => { const e = document.scrollingElement; return e.scrollHeight === e.clientHeight; });
  assert.ok(s, "page does not scroll");
  assert.deepEqual(errors, [], "page errors: " + errors.join("; "));
  ok("no page errors, page does not scroll");
  console.log(`\nE2E PASSED: ${passed} checks`);
} catch (e) {
  console.error("E2E FAILED after", passed, "checks:", e.message);
  process.exitCode = 1;
} finally {
  await browser.close().catch(() => {});
  procs.forEach(p => { try { p.kill(); } catch {} });
  fs.rmSync(data, { recursive: true, force: true, maxRetries: 3 });
}
process.exit(process.exitCode || 0);
