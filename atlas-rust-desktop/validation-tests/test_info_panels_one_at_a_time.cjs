// Header panels (plugins, MCP, usage, memory): opening one closes the others. Run: node test_info_panels_one_at_a_time.cjs
const fs = require("fs"), path = require("path"), assert = require("assert");
const src = fs.readFileSync(path.join(__dirname, "..", "src-tauri", "resources", "atlas", "index.html"), "utf8").replace(/\r\n/g, "\n");
const code = src.match(/const infoPanels=[\s\S]*?\nfunction arrangeInfoPanels\(active\)\{[\s\S]*?\n\}\n/)[0];

const els = {};
const el = id => els[id] ??= { open: false, attrs: {}, style: {},
  classList: { contains: c => c === "open" && els[id].open, remove: c => { if (c === "open") els[id].open = false; } },
  setAttribute(k, v) { this.attrs[k] = v; } };
const $ = sel => el(sel.slice(1));
const arrangeInfoPanels = new Function("$", code + "\nreturn arrangeInfoPanels;")($);

el("mcpPanel").open = true; el("usagePanel").open = true; el("syncPanel").open = true; el("pluginsPanel").open = true;
arrangeInfoPanels("pluginsPanel");
assert.deepStrictEqual(["pluginsPanel", "mcpPanel", "usagePanel", "memoryPanel", "syncPanel"].map(id => el(id).open), [true, false, false, false, false]);
assert.strictEqual(el("pluginsBtn").attrs["aria-expanded"], "true");
assert.strictEqual(el("mcpBtn").attrs["aria-expanded"], "false");

el("pluginsPanel").open = false; arrangeInfoPanels();  // a close button: nothing else opens
assert.ok(["pluginsPanel", "mcpPanel", "usagePanel", "memoryPanel", "syncPanel"].every(id => !el(id).open));
assert.strictEqual(el("pluginsBtn").attrs["aria-expanded"], "false");
console.log("ok: one info panel at a time");
