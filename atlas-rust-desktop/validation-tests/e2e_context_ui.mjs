// End-to-end: real server.py + real index.html in Chromium, against fake_llama_swap.py (1 token = 4 chars).
// Checks: real n_ctx in the CTX meter, exact token counts, /remember memory, slash hints, retry, edit, branch,
// chat search, /compact, phone width. Run from anywhere:  node atlas-rust-desktop/validation-tests/e2e_context_ui.mjs
// Needs Python 3 and Playwright (require('playwright')). Writes screenshots to $E2E_SHOTS (optional).
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require(require.resolve("playwright", { paths: ["/opt/node22/lib/node_modules", "/usr/local/lib/node_modules", "/usr/lib/node_modules"] }))); }

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.join(HERE, "..", "src-tauri", "resources", "atlas");
const FAKE_PORT = 18411, APP_PORT = 18412;
const data = fs.mkdtempSync(path.join(os.tmpdir(), "atlas-e2e-"));
fs.writeFileSync(path.join(data, "settings.json"), JSON.stringify({ server_port: APP_PORT, upstream_port: FAKE_PORT, embedding_model: "", mcp_auto_tools: false }));
const py = process.platform === "win32" ? "python" : "python3";
const procs = [
  spawn(py, [path.join(HERE, "fake_llama_swap.py"), String(FAKE_PORT), "8192"], { stdio: "inherit" }),
  spawn(py, ["server.py"], { cwd: APP, env: { ...process.env, ATLAS_DATA_DIR: data, ATLAS_OBSERVABILITY_DB: path.join(data, "obs.sqlite3") }, stdio: ["ignore", "ignore", "inherit"] }),
];
const stop = () => procs.forEach(p => { try { p.kill(); } catch {} });
process.on("exit", stop);
const wait = async (url) => { for (let i = 0; i < 100; i++) { try { const r = await fetch(url); if (r.ok) return; } catch {} await new Promise(r => setTimeout(r, 150)); } throw new Error("not up: " + url); };
const shots = process.env.E2E_SHOTS || "";
const fakeTemplate = msgs => msgs.map(m => `<|${m.role}|>${typeof m.content === "string" ? m.content : m.content.filter(p => p.type === "text").map(p => p.text).join("\n")}<|end|>`).join("") + "<|assistant|>";

let passed = 0; const ok = name => { passed++; console.log("ok -", name); };
try {
  await wait(`http://127.0.0.1:${FAKE_PORT}/health`);
  await wait(`http://127.0.0.1:${APP_PORT}/`);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("dialog", d => d.accept());
  await page.goto(`http://127.0.0.1:${APP_PORT}/`);
  await page.waitForFunction(() => document.querySelector("#hdrModel option[value='assist']"));
  await page.selectOption("#hdrModel", "assist");
  ok("app loads and lists the fake models");

  const send = async (text) => {
    const before = await page.evaluate(() => (chat()?.messages || []).filter(m => m.role === "assistant").length);
    await page.fill("#input", text); await page.press("#input", "Enter");
    await page.waitForFunction(n => (chat()?.messages || []).filter(m => m.role === "assistant").length > n && !ctrl, before, { timeout: 20000 });
    return page.evaluate(() => chat().messages.at(-1));
  };
  const lastUpstream = async () => (await (await fetch(`http://127.0.0.1:${FAKE_PORT}/_last`)).json()).chat;

  // 1. Real window + exact count
  let reply = await send("Hello Atlas, please introduce yourself in one line.");
  assert.match(reply.content, /Reply to: Hello Atlas/);
  const sent = await lastUpstream();
  const exact = Math.ceil(fakeTemplate(sent.messages).length / 4);
  assert.equal(reply.usage.prompt, exact, "prompt tokens = fake tokenizer count");
  assert.equal(reply.usage.source, "exact");
  assert.ok(reply.usage.completion > 0);
  const meter = await page.textContent("#usageBtn");
  assert.match(meter, new RegExp(`CTX ${(exact + reply.usage.completion).toLocaleString("en-US")} / 8,192`), meter);
  assert.match(reply.stats, /prompt \d+ tokens \(\d+ cached\)/);
  ok(`CTX meter uses llama-server n_ctx 8,192 and exact prompt ${exact} tokens: "${meter}"`);
  await page.click("#usageBtn");
  assert.match(await page.textContent("#ctxSource"), /EXACT/);
  assert.match(await page.textContent("#ctxBreakdown"), /Conversation/);
  if (shots) await page.screenshot({ path: path.join(shots, "context-panel.png") });
  await page.click("#usageClose");
  ok("usage panel shows EXACT source and breakdown");

  // 2. Memory via /remember
  await page.fill("#input", "/remember I like short numbered steps");
  await page.press("#input", "Enter");
  await page.waitForFunction(() => /MEMORY \/\/ 1/.test(document.querySelector("#memoryBtn").textContent));
  assert.match(await page.textContent(".chat-note:last-of-type"), /Saved to memory/);
  reply = await send("What format do I like?");
  assert.match(reply.content, /memory=yes/);
  assert.match(reply.stats, /memory: 1/);
  ok("/remember saves memory and the next prompt carries it");
  await page.click("#memoryBtn");
  assert.match(await page.textContent("#memoryList"), /short numbered steps/);
  if (shots) await page.screenshot({ path: path.join(shots, "memory-panel.png") });
  await page.click("#memoryClose");
  ok("memory panel lists the item");

  // 3. Slash hints
  await page.fill("#input", "");
  await page.type("#input", "/co");
  await page.waitForSelector("#slashHints:not([hidden]) li");
  const hints = await page.$$eval("#slashHints li b", els => els.map(e => e.textContent));
  assert.deepEqual(hints, ["/compact", "/context"]);
  await page.keyboard.press("Escape"); await page.fill("#input", "");
  ok("slash hints filter as you type");

  // 4. Retry keeps the message count
  const count = await page.evaluate(() => chat().messages.length);
  await page.locator("#log .msg.assistant").last().getByRole("button", { name: "RETRY" }).click();
  await page.waitForFunction(n => chat().messages.length === n && !ctrl && chat().messages.at(-1).role === "assistant", count, { timeout: 20000 });
  ok("RETRY regenerates the last answer in place");

  // 5. Edit the first message: later messages are replaced
  await page.locator("#log .msg.user").first().getByRole("button", { name: "EDIT" }).click();
  await page.fill("#log .msg-edit", "Edited first question about the VIP store");
  await page.click("text=SAVE & SEND");
  await page.waitForFunction(() => chat().messages.length === 2 && !ctrl && chat().messages[1].role === "assistant", null, { timeout: 20000 });
  assert.match(await page.evaluate(() => chat().messages[1].content), /Edited first question/);
  ok("EDIT resends from that message and drops the later ones");

  // 6. Branch + search
  await page.locator("#log .msg.assistant").last().getByRole("button", { name: "BRANCH" }).click();
  await page.waitForFunction(() => /^↳ /.test(chat().title) && chat().messages.length === 2);
  await page.fill("#chatSearch", "zzz-no-such-chat");
  assert.match(await page.textContent("#chats"), /No chats match/);
  await page.fill("#chatSearch", "VIP store");
  assert.ok((await page.$$("#chats li button.open")).length >= 2);
  await page.fill("#chatSearch", ""); await page.dispatchEvent("#chatSearch", "input");
  ok("BRANCH makes a new chat; search filters by title and content");

  // 7. /compact
  await send("Second topic: shipping rules for the store.");
  await send("Third topic: refunds.");
  await page.fill("#input", "/compact"); await page.press("#input", "Enter");
  await page.waitForSelector(".compact-mark", { timeout: 20000 });
  const upto = await page.evaluate(() => chat().compact.upto);
  assert.ok(upto >= 2);
  reply = await send("What did we talk about first?");
  assert.match(reply.content, /summary=yes/);
  const after = await lastUpstream();
  assert.equal(after.messages.filter(m => m.role !== "system").length, (await page.evaluate(() => chat().messages.length)) - upto - 1);
  ok(`/compact summarises ${upto} messages; later prompts send the summary instead of them`);

  // 8. Phone width
  await page.setViewportSize({ width: 390, height: 844 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  assert.ok(overflow <= 1, "no horizontal scroll at phone width: " + overflow);
  if (shots) await page.screenshot({ path: path.join(shots, "phone.png") });
  ok("phone width has no horizontal scroll");

  assert.deepEqual(errors, [], "page errors: " + errors.join("; "));
  ok("no page errors");
  await browser.close();
  console.log(`\nE2E PASSED: ${passed} checks`);
} catch (e) {
  console.error("E2E FAILED after", passed, "checks:", e.message);
  process.exitCode = 1;
} finally { stop(); fs.rmSync(data, { recursive: true, force: true }); }
