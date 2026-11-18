// UI and accessibility contracts from the 2026-11-18 review (UI-A11Y-2026-11-18.md).
// Run: node validation-tests/test_ui_a11y.js   (from atlas-rust-desktop, or any folder)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');
const html = read('src-tauri/resources/atlas/index.html');
const app = read('src/App.tsx');
const css = read('src/atlas-node.css');
const rust = read('src-tauri/src/telemetry.rs');
const main = read('src-tauri/src/main.rs');

// The "#log *{user-select:text !important}" rule wins over any later non-important rule,
// so the rule that keeps queue buttons out of a selection must be !important and come after it.
const textAll = html.indexOf('#log,#log *,#log .msg');
const noneRule = /#log button,#log button \*,#log \.queue-strip,#log \.queue-strip \*[^{]*\{-webkit-user-select:none !important;user-select:none !important\}/.exec(html);

const opsRefresh = app.slice(app.indexOf('function OperationsDashboard'), app.indexOf('const loadDiagnostics'));

const checks = [
  ['queue buttons (PAUSE AUTO / SEND NEXT / CLEAR) never join a chat text selection', textAll > 0 && !!noneRule && noneRule.index > textAll],
  ['bot cards are plain buttons, not role=listitem', !/setAttribute\("role","listitem"\)/.test(html) && !/id="bots"[^>]*role="list"/.test(html)],
  ['bot cards have a short name and a keyboard reorder (Alt+Up/Down)', /el\.setAttribute\("aria-label", `\$\{b\.name/.test(html) && /e\.altKey[\s\S]{0,120}ArrowUp/.test(html)],
  ['knowledge library fields have labels', ['browserChatUrl', 'browserChatText', 'knowledgeQuery'].every(id => new RegExp(`id="${id}" aria-label="`).test(html))],
  ['gpu_telemetry command is registered and runs off the UI thread', /gpu_telemetry,/.test(main) && /async fn gpu_telemetry[\s\S]{0,200}spawn_blocking\(telemetry::gpu_live\)/.test(main)],
  ['GPU utilisation is the busiest engine (Task Manager method), unit-tested', /fn busiest_engine_wins_and_processes_add_up/.test(rust)],
  ['Operations reads GPU next to CPU/RAM and skips polls while hidden', /invoke<GpuLive\[\]>\('gpu_telemetry'\)/.test(opsRefresh) && /if\(!document\.hidden\)void refresh\(\)/.test(opsRefresh)],
  ['Operations does not re-list models on every 3 s poll', !/node_local_models/.test(opsRefresh.slice(opsRefresh.indexOf('const refresh=')))],
  ['GPU card sits in the CPU / RAM summary row', /<section className="node-summary ops-summary">[\s\S]*?className="ops-gpu"[\s\S]*?<\/section>/.test(app)],
  ['start-screen metrics stop once the app is ready', /ready\?15000:2500/.test(app)],
  ['React frame has a visible focus ring and honours reduced motion', /:focus-visible\{outline:2px solid/.test(css) && /prefers-reduced-motion:reduce/.test(css)],
  ['Node page: sliders and model picker are labelled', /aria-label="CPU ceiling"/.test(app) && /aria-label="Memory ceiling"/.test(app) && /aria-label="Local model to benchmark"/.test(app)],
  ['Node page: unsaved policy changes are announced', /className="node-unsaved" role="status"/.test(app)],
  ['top navigation marks the current page', /aria-current=\{view==='ops'\?'page':undefined\}/.test(app)],
  ['React frame shell scrolls on small windows and node-page avoids 100vh', /\.shell\{[^}]*overflow:auto/.test(read('src/style.css')) && !/100vh/.test(css)],
  ['Escape closes open info panels and execution panel', /e\.key!=="Escape"/.test(html) && /toggleExecutionPanel\(false\)/.test(html)],
  ['execution log reads active chat id instead of missing data attribute', /chat\(\)\?\.id\s*\|\|\s*S\.chat/.test(html) && !/data-current-chat/.test(html)],
];
let failed = 0;
for (const [name, ok] of checks) { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`); if (!ok) failed++; }
process.exit(failed ? 1 : 0);
