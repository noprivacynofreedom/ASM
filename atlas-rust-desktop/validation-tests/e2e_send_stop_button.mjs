// Live headless Chromium E2E test for normal-chat Send / Stop button visibility, hit-testing, and runtime lifecycle.
// Zero npm dependencies: uses Node 22/24 built-in WebSocket + local Chromium via CDP against live server.py + fake_llama_swap.py.
// Run from anywhere:  node atlas-rust-desktop/validation-tests/e2e_send_stop_button.mjs
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.join(HERE, "..", "src-tauri", "resources", "atlas");
const FAKE_PORT = 18531;
const APP_PORT = 18532;
const CDP_PORT = 18533;

function findBrowser() {
  const candidates = [
    process.env.CHROME_BIN,
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  ].filter(Boolean);
  return candidates.find(p => fs.existsSync(p)) || null;
}

const browserBin = findBrowser();
if (!browserBin) {
  console.error("FAIL: no Chromium/Chrome/Edge binary found (set CHROME_BIN to override)");
  process.exit(1);
}

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "atlas-stop-e2e-"));
const userData = fs.mkdtempSync(path.join(os.tmpdir(), "atlas-stop-chrome-"));
fs.writeFileSync(
  path.join(dataDir, "settings.json"),
  JSON.stringify({ server_port: APP_PORT, upstream_port: FAKE_PORT, embedding_model: "", mcp_auto_tools: false })
);

const py = process.platform === "win32" ? "python" : "python3";
const procs = [];
const cleanup = () => {
  for (const p of procs) { try { p.kill("SIGKILL"); } catch {} }
  try { fs.rmSync(dataDir, { recursive: true, force: true }); } catch {}
  try { fs.rmSync(userData, { recursive: true, force: true }); } catch {}
};
process.on("exit", cleanup);
process.on("SIGINT", () => { cleanup(); process.exit(1); });

procs.push(spawn(py, [path.join(HERE, "fake_llama_swap.py"), String(FAKE_PORT), "8192"], { stdio: "ignore" }));
procs.push(spawn(py, ["server.py"], {
  cwd: APP,
  env: { ...process.env, ATLAS_DATA_DIR: dataDir, ATLAS_OBSERVABILITY_DB: path.join(dataDir, "o.sqlite3") },
  stdio: "ignore",
}));

let ready = false;
for (let i = 0; i < 100; i++) {
  try { if ((await fetch(`http://127.0.0.1:${APP_PORT}/`)).ok) { ready = true; break; } } catch {}
  await new Promise(r => setTimeout(r, 100));
}
if (!ready) throw new Error("server.py did not start in time");

procs.push(spawn(browserBin, [
  "--headless=new",
  "--no-sandbox",
  "--disable-gpu",
  "--disable-dev-shm-usage",
  `--remote-debugging-port=${CDP_PORT}`,
  `--user-data-dir=${userData}`,
  "about:blank",
], { stdio: "ignore" }));

let wsUrl = null;
for (let i = 0; i < 100; i++) {
  try {
    const targets = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
    const page = targets.find(t => t.type === "page" && t.webSocketDebuggerUrl);
    if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
  } catch {}
  await new Promise(r => setTimeout(r, 100));
}
if (!wsUrl) throw new Error("Chromium CDP failed to start");

class CDP {
  constructor(url) {
    this.id = 0;
    this.pending = new Map();
    this.events = [];
    this.ws = new WebSocket(url);
    this.ready = new Promise((res, rej) => {
      this.ws.addEventListener("open", res);
      this.ws.addEventListener("error", rej);
    });
    this.ws.addEventListener("message", ev => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { res, rej } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) rej(new Error(msg.error.message));
        else res(msg.result);
      } else if (msg.method) {
        this.events.push(msg);
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((res, rej) => this.pending.set(id, { res, rej }));
  }
  async eval(expr) {
    const r = await this.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) {
      throw new Error(r.exceptionDetails.text + " " + (r.exceptionDetails.exception?.description || JSON.stringify(r.exceptionDetails)));
    }
    return r.result?.value;
  }
  close() { try { this.ws.close(); } catch {} }
}

const failures = [];
function assert(cond, msg) {
  if (!cond) {
    failures.push(msg);
    console.error("FAIL:", msg);
  } else {
    console.log("PASS:", msg);
  }
}

const cdp = new CDP(wsUrl);
await cdp.ready;
await cdp.send("Page.enable");
await cdp.send("Runtime.enable");
await cdp.send("Console.enable");
await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false });

await cdp.send("Page.navigate", { url: `http://127.0.0.1:${APP_PORT}/` });
for (let i = 0; i < 60; i++) {
  const loaded = await cdp.eval(`typeof syncComposerButtons === "function" && !!document.querySelector("#hdrModel option[value='assist']")`).catch(() => false);
  if (loaded) break;
  await new Promise(r => setTimeout(r, 100));
}

const pageErrors = cdp.events
  .filter(e => e.method === "Runtime.exceptionThrown" || (e.method === "Console.messageAdded" && e.params.message.level === "error"))
  .map(e => e.method === "Runtime.exceptionThrown"
    ? `${e.params.exceptionDetails.text} line ${e.params.exceptionDetails.lineNumber}: ${e.params.exceptionDetails.exception?.description || ""}`
    : e.params.message.text);
assert(pageErrors.length === 0, `zero page/console errors on load (got: ${JSON.stringify(pageErrors)})`);

// 1. Layout, clipping, non-scrolling, and elementFromPoint hit-testing across viewports + DSF scaling + heavy stacked panels (including #brBtn + #ghBtn)
const viewports = [
  [1400, 900, 1],
  [1400, 900, 1.25],
  [1400, 900, 1.5],
  [1280, 720, 1],
  [1280, 720, 1.25],
  [1280, 720, 1.5],
  [1240, 800, 1],
  [1200, 800, 1],
  [1150, 750, 1],
  [1100, 750, 1],
  [1024, 768, 1],
  [820, 700, 1],
  [390, 800, 1],
  [320, 600, 1],
];

const layoutStates = [
  {
    name: "baseline-send",
    setup: `(() => {
      document.querySelector("#send").hidden = false;
      document.querySelector("#stop").hidden = true;
      document.querySelector("#files").innerHTML = "";
      document.querySelector("#activityCompanion").hidden = true;
      document.querySelector("#swarmBar").hidden = true;
      document.querySelector("#approvals").hidden = true;
      document.querySelector("#input").style.height = "";
      document.querySelector("#brState").textContent = "sandbox";
      const gh = document.querySelector("#ghState"); if (gh) gh.textContent = "on";
    })()`,
  },
  {
    name: "heavy-panels-stop-max-resized-input",
    setup: `(() => {
      document.querySelector("#send").hidden = true;
      document.querySelector("#stop").hidden = false;
      document.querySelector("#brState").textContent = "sandbox";
      const gh = document.querySelector("#ghState"); if (gh) gh.textContent = "on";
      document.querySelector("#voice").textContent = "Stop mic 0:15";
      document.querySelector("#files").innerHTML = Array.from({length: 12}, (_, i) => '<span class="file-chip"><span>attachment_' + i + '_very_long_filename.png</span><button type="button">x</button></span>').join("");
      document.querySelector("#activityCompanion").hidden = false;
      document.querySelector("#activityDetails").hidden = false;
      document.querySelector("#activityEvents").innerHTML = Array.from({length: 10}, (_, i) => '<div class="activity-event"><b>Event ' + i + '</b></div>').join("");
      document.querySelector("#swarmBar").hidden = false;
      document.querySelector("#swarmBar").textContent = "SWARM running ".repeat(20);
      document.querySelector("#approvals").hidden = false;
      document.querySelector("#approvals").innerHTML = Array.from({length: 4}, (_, i) => '<div class="approval"><b>Approve tool ' + i + '</b><div class="args">' + 'x'.repeat(200) + '</div></div>').join("");
      document.querySelector("#input").style.height = "600px";
    })()`,
  },
];

let layoutBad = 0;
for (const state of layoutStates) {
  for (const [w, h, dsf] of viewports) {
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: dsf, mobile: false });
    await cdp.eval(state.setup);
    await new Promise(r => setTimeout(r, 40));
    const m = await cdp.eval(`(() => {
      const s = document.scrollingElement;
      const main = document.querySelector("main").getBoundingClientRect();
      const send = document.querySelector("#send"), stop = document.querySelector("#stop");
      const btn = send.hidden ? stop : send;
      const r = btn.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const hit = document.elementFromPoint(cx, cy);
      const hitOk = !!(hit && (hit === btn || btn.contains(hit)));
      return {
        btn: btn.id,
        l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height,
        mainL: main.left, mainR: main.right, mainT: main.top, mainB: main.bottom,
        iw: innerWidth, ih: innerHeight,
        sh: s.scrollHeight, ch: s.clientHeight, sw: s.scrollWidth, cw: s.clientWidth,
        hitOk, hitTag: hit ? (hit.id || hit.className || hit.tagName) : null
      };
    })()`);
    const ok =
      m.w >= 40 && m.h >= 20 &&
      m.l >= Math.max(0, m.mainL) - 0.5 &&
      m.r <= Math.min(m.iw, m.mainR) + 0.5 &&
      m.t >= Math.max(0, m.mainT) - 0.5 &&
      m.b <= Math.min(m.ih, m.mainB) + 0.5 &&
      m.sh === m.ch && m.sw <= m.cw &&
      m.hitOk;
    if (!ok) {
      layoutBad++;
      console.error(`LAYOUT FAIL [${state.name}] ${w}x${h}@${dsf}:`, JSON.stringify(m));
    }
  }
}
assert(layoutBad === 0, `all ${layoutStates.length * viewports.length} viewport/DSF/heavy-panel checks pass with hit-test & zero scroll`);

// Reset to desktop size for overlay and runtime flow checks
await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 720, deviceScaleFactor: 1, mobile: false });
await cdp.eval(`(() => {
  document.querySelector("#files").innerHTML = "";
  document.querySelector("#activityCompanion").hidden = true;
  document.querySelector("#swarmBar").hidden = true;
  document.querySelector("#approvals").hidden = true;
  document.querySelector("#input").style.height = "";
  document.querySelector("#voice").textContent = "Mic";
  syncComposerButtons();
})()`);

// 2. Hit-testing with #atomicToast visible AND faded out, plus #atlasDevFab enabled
const overlayCheck = await cdp.eval(`(async () => {
  const c1 = chat() || newChat();
  atomicTransition(c1, { id: "next-test", title: "Isolated topic" });
  await new Promise(r => setTimeout(r, 80));
  const checkBtn = (isStop) => {
    document.querySelector("#send").hidden = isStop;
    document.querySelector("#stop").hidden = !isStop;
    const btn = isStop ? document.querySelector("#stop") : document.querySelector("#send");
    const r = btn.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    const toast = document.querySelector("#atomicToast").getBoundingClientRect();
    const overlapsToast = !(r.right <= toast.left || r.left >= toast.right || r.bottom <= toast.top || r.top >= toast.bottom);
    return { hitOk: !!(hit && (hit === btn || btn.contains(hit))), hitId: hit?.id || hit?.tagName, overlapsToast };
  };
  const whileToastShownSend = checkBtn(false);
  const whileToastShownStop = checkBtn(true);
  document.querySelector("#atomicToast").classList.remove("show");
  await new Promise(r => setTimeout(r, 260));
  const toastStyle = getComputedStyle(document.querySelector("#atomicToast"));
  const afterToastHiddenStop = checkBtn(true);
  document.documentElement.dataset.devTools = "true";
  const withDevFabStop = checkBtn(true);
  const withDevFabSend = checkBtn(false);
  document.documentElement.dataset.devTools = "";
  syncComposerButtons();
  return {
    whileToastShownSend, whileToastShownStop, afterToastHiddenStop,
    toastHiddenPointerEvents: toastStyle.pointerEvents,
    toastHiddenVisibility: toastStyle.visibility,
    withDevFabStop, withDevFabSend
  };
})()`);
assert(overlayCheck.whileToastShownSend.hitOk && !overlayCheck.whileToastShownSend.overlapsToast, "#atomicToast.show never covers or intercepts #send");
assert(overlayCheck.whileToastShownStop.hitOk && !overlayCheck.whileToastShownStop.overlapsToast, "#atomicToast.show never covers or intercepts #stop");
assert(overlayCheck.afterToastHiddenStop.hitOk && overlayCheck.toastHiddenPointerEvents === "none", "hidden #atomicToast has pointer-events:none and never intercepts #stop");
assert(overlayCheck.withDevFabStop.hitOk && overlayCheck.withDevFabSend.hitOk, "#atlasDevFab never covers or intercepts #send or #stop");

// 3. Live runtime flow checks: streaming + showPage round-trip + Stop abort + vision gap/race + auto-compact + manual /compact + zero-flicker queue handoff
const runtimeResults = await cdp.eval(`(async () => {
  const origFetch = window.fetch.bind(window);
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const sseResponse = (chunks, delayMs = 60, signal) => {
    const enc = new TextEncoder();
    let idx = 0;
    const stream = new ReadableStream({
      async pull(controller) {
        if (signal && signal.aborted) { controller.error(new DOMException("Aborted", "AbortError")); return; }
        if (idx >= chunks.length) {
          controller.enqueue(enc.encode("data: [DONE]\\n\\n"));
          controller.close();
          return;
        }
        await new Promise((res, rej) => {
          const t = setTimeout(res, delayMs);
          if (signal) signal.addEventListener("abort", () => { clearTimeout(t); rej(new DOMException("Aborted", "AbortError")); }, { once: true });
        });
        controller.enqueue(enc.encode("data: " + JSON.stringify({ choices: [{ delta: { content: chunks[idx++] } }] }) + "\\n\\n"));
      }
    });
    return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
  };

  let mode = "passthrough";
  let chatCalls = 0;
  let confirmCalled = false;
  const origConfirm = window.confirm;
  window.confirm = () => { confirmCalled = true; return false; };

  window.fetch = async (url, init = {}) => {
    const u = String(url);
    if (mode === "slow-stream" && u.includes("/v1/chat/completions")) {
      chatCalls++;
      return sseResponse(["hello ", "world ", "from ", "stream"], 120, init.signal);
    }
    if (mode === "slow-vision" && u.includes("/api/vision")) {
      return await new Promise((res, rej) => {
        const t = setTimeout(() => res(new Response(JSON.stringify({ vision: true }), { status: 200, headers: { "Content-Type": "application/json" } })), 600);
        if (init.signal) init.signal.addEventListener("abort", () => { clearTimeout(t); rej(new DOMException("Aborted", "AbortError")); }, { once: true });
      });
    }
    if (mode === "slow-compact" && u.includes("/api/context/compact")) {
      return await new Promise((res, rej) => {
        const t = setTimeout(() => res(new Response(JSON.stringify({ ok: true, summary: "short summary" }), { status: 200, headers: { "Content-Type": "application/json" } })), 600);
        if (init.signal) init.signal.addEventListener("abort", () => { clearTimeout(t); rej(new DOMException("Aborted", "AbortError")); }, { once: true });
      });
    }
    if (mode === "slow-compact" && u.includes("/v1/chat/completions")) {
      chatCalls++;
      return sseResponse(["should not run"], 50, init.signal);
    }
    if (mode === "queue-stream" && u.includes("/v1/chat/completions")) {
      chatCalls++;
      return sseResponse(["msg" + chatCalls + " ", "done"], 80, init.signal);
    }
    return origFetch(url, init);
  };

  const out = {};
  try {
    // Flow 1: slow stream + showPage('ops') -> showPage('chat') + click Stop
    mode = "slow-stream";
    newChat();
    const p1 = send("stream test");
    await wait(50);
    const stopImmediately = !$("#stop").hidden && $("#send").hidden;
    showPage("ops");
    await wait(20);
    showPage("chat");
    const stopAfterPageSwitch = !$("#stop").hidden && $("#send").hidden && getComputedStyle($("#files")).display === "none";
    $("#stop").click();
    const res1 = await p1;
    const sendRestored1 = !$("#send").hidden && $("#stop").hidden && ctrl === null;
    out.flow1 = { stopImmediately, stopAfterPageSwitch, res1, sendRestored1 };

    // Flow 2: slow /api/vision + concurrent send("second") guard + Stop during vision check
    mode = "slow-vision";
    confirmCalled = false;
    bot().imageSupport = "unknown";
    const p2 = send("describe pic", { attachments: [{ name: "a.png", data: "data:image/png;base64,iVBORw0KGgo=" }] });
    await wait(40);
    const stopDuringVision = !$("#stop").hidden && $("#send").hidden;
    const concurrentRes = await send("concurrent attempt");
    const stopStillUpAfterRace = !$("#stop").hidden && $("#send").hidden;
    $("#stop").click();
    const res2 = await p2;
    const sendRestored2 = !$("#send").hidden && $("#stop").hidden && ctrl === null && !confirmCalled;
    out.flow2 = { stopDuringVision, concurrentRes, stopStillUpAfterRace, res2, sendRestored2 };

    // Flow 3: auto-compact Stop aborts compaction and never calls /v1/chat/completions
    mode = "slow-compact";
    chatCalls = 0;
    const c3 = newChat();
    bot().context_length = 2048;
    bot().max_tokens = 512;
    for (let i = 0; i < 10; i++) c3.messages.push({ role: i % 2 ? "assistant" : "user", content: "word ".repeat(300) + i, at: Date.now() });
    const p3 = send("trigger auto compact", { noAtomic: true });
    await wait(40);
    const stopDuringAutoCompact = !$("#stop").hidden && $("#send").hidden;
    $("#stop").click();
    const res3 = await p3;
    const sendRestored3 = !$("#send").hidden && $("#stop").hidden && ctrl === null && chatCalls === 0;
    out.flow3 = { stopDuringAutoCompact, res3, sendRestored3 };

    // Flow 4: manual /compact shows Stop and aborts cleanly
    mode = "slow-compact";
    const p4 = runSlash("/compact");
    await wait(40);
    const stopDuringManualCompact = !$("#stop").hidden && $("#send").hidden;
    $("#stop").click();
    const res4 = await p4;
    const sendRestored4 = !$("#send").hidden && $("#stop").hidden && ctrl === null;
    out.flow4 = { stopDuringManualCompact, res4, sendRestored4 };

    // Flow 5: queue handoff keeps #stop visible across msg1 -> msg2 with zero flicker (even single-tick)
    mode = "queue-stream";
    chatCalls = 0;
    bot().context_length = 32768;
    S.queue = []; S.queuePaused = false;
    newChat();
    const transitions = [];
    const mo = new MutationObserver(() => {
      transitions.push({ stopHidden: $("#stop").hidden, sendHidden: $("#send").hidden, chatCalls, queueLen: S.queue.length });
    });
    mo.observe($("#stop"), { attributes: true, attributeFilter: ["hidden"] });
    const p5 = send("first queued flow", { noAtomic: true });
    await wait(30);
    $("#input").value = "second queued flow";
    $("#form").requestSubmit();
    const queuedCount = S.queue.length;
    await p5;
    for (let i = 0; i < 100 && (ctrl || queueRunning || queueDrainPromise || S.queue.length); i++) await wait(20);
    mo.disconnect();
    const hideEvents = transitions.filter(t => t.stopHidden);
    const stopDroppedMidQueue = hideEvents.length !== 1 || hideEvents[0].chatCalls < 2 || hideEvents[0].queueLen !== 0;
    const sendRestored5 = !$("#send").hidden && $("#stop").hidden && ctrl === null && S.queue.length === 0 && chatCalls === 2;
    out.flow5 = { queuedCount, stopDroppedMidQueue, hideCount: hideEvents.length, transitions, sendRestored5, chatCalls };
  } finally {
    window.fetch = origFetch;
    window.confirm = origConfirm;
  }
  return out;
})()`);

assert(
  runtimeResults.flow1.stopImmediately && runtimeResults.flow1.stopAfterPageSwitch && runtimeResults.flow1.res1 === "STOPPED" && runtimeResults.flow1.sendRestored1,
  `Flow 1 (stream + showPage switch + Stop abort): ${JSON.stringify(runtimeResults.flow1)}`
);
assert(
  runtimeResults.flow2.stopDuringVision && runtimeResults.flow2.concurrentRes === "BUSY" && runtimeResults.flow2.stopStillUpAfterRace && runtimeResults.flow2.res2 === "STOPPED" && runtimeResults.flow2.sendRestored2,
  `Flow 2 (slow /api/vision + concurrent send race + Stop): ${JSON.stringify(runtimeResults.flow2)}`
);
assert(
  runtimeResults.flow3.stopDuringAutoCompact && runtimeResults.flow3.res3 === "STOPPED" && runtimeResults.flow3.sendRestored3,
  `Flow 3 (auto-compact Stop aborts before chat completion): ${JSON.stringify(runtimeResults.flow3)}`
);
assert(
  runtimeResults.flow4.stopDuringManualCompact && runtimeResults.flow4.res4 === "STOPPED" && runtimeResults.flow4.sendRestored4,
  `Flow 4 (manual /compact Stop aborts cleanly): ${JSON.stringify(runtimeResults.flow4)}`
);
assert(
  runtimeResults.flow5.queuedCount === 1 && !runtimeResults.flow5.stopDroppedMidQueue && runtimeResults.flow5.sendRestored5,
  `Flow 5 (queue handoff keeps #stop continuously visible across messages): ${JSON.stringify(runtimeResults.flow5)}`
);

cdp.close();
if (failures.length) {
  console.error(`\nE2E FAILED (${failures.length} failure(s))`);
  process.exit(1);
}
console.log("\nE2E PASSED: Send/Stop button stays visible, clickable, and in sync across all layouts, overlays, and async flows.");
process.exit(0);
