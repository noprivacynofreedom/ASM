/* Atlas Bot Logs: a page inside the llama-swap dashboard (Operations > llama-swap).
   hw_proxy.py injects this file into llama-swap's /ui/ page and serves the data at /__atlas/bot-logs.json.
   It adds "Bot Logs" to the sidebar between Playground and Models, and opens at #/atlas-bot-logs.
   Each swarm Lead and each bot chat gets a colour by its backend state. Finished runs move to the
   Archive, grouped by category, each category with its own calm colour. No llama-swap code is changed. */
(function () {
  "use strict";
  var ROUTE = "#/atlas-bot-logs";
  var STATE = {
    queued: { c: "#60a5fa", w: "Queued", m: "○" },
    running: { c: "#f59e0b", w: "Running", m: "●" },
    stalled: { c: "#fb923c", w: "Stalled", m: "!" },
    done: { c: "#22c55e", w: "Done", m: "✓" },
    failed: { c: "#ef4444", w: "Failed", m: "✕" },
    timeout: { c: "#e879f9", w: "Timed out", m: "⧗" },
    cancelled: { c: "#9ca3af", w: "Stopped", m: "■" }
  };
  var CATEGORY = {
    code: { c: "#2dd4bf", w: "Code" }, research: { c: "#a78bfa", w: "Research" }, writing: { c: "#f9a8d4", w: "Writing" },
    data: { c: "#38bdf8", w: "Data" }, design: { c: "#fcd34d", w: "Design" }, other: { c: "#94a3b8", w: "Other" }
  };
  var view = { filter: "all", query: "", open: {}, catOpen: {}, data: null, lastJson: "", error: "", timer: null, searchTimer: null, titleNode: null, titleText: "" };

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (ch) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]; }); }
  function onPage() { return location.hash.indexOf(ROUTE) === 0; }
  function runParam() { var m = /[?&]run=([^&]+)/.exec(location.hash); return m ? decodeURIComponent(m[1]) : ""; }
  function clock(ts) { return new Date(ts * 1000).toLocaleTimeString(); }
  function dur(s) { s = Math.round(s || 0); return s < 60 ? s + "s" : s < 3600 ? Math.floor(s / 60) + "m " + (s % 60) + "s" : Math.floor(s / 3600) + "h " + Math.floor(s % 3600 / 60) + "m"; }

  var css = document.createElement("style");
  css.textContent = [
    "#atlas-botlogs{position:absolute;left:0;right:0;bottom:0;overflow:auto;background:var(--background);color:var(--foreground);z-index:20;padding:16px;font-size:14px}",
    "#atlas-botlogs[hidden]{display:none}",
    "#atlas-botlogs .bl-wrap{max-width:1100px;margin:0 auto;display:flex;flex-direction:column;gap:12px}",
    "#atlas-botlogs .bl-top{display:flex;flex-wrap:wrap;gap:8px;align-items:center}",
    "#atlas-botlogs h2{font-size:16px;font-weight:600;margin:0;flex:1 1 auto}",
    "#atlas-botlogs h3{font-size:13px;font-weight:600;margin:12px 0 0;color:var(--muted-foreground);text-transform:uppercase;letter-spacing:.04em}",
    "#atlas-botlogs button{font:inherit;color:inherit;cursor:pointer;background:transparent;border:1px solid var(--border);border-radius:6px;padding:4px 10px}",
    "#atlas-botlogs button:hover{background:var(--accent)}",
    "#atlas-botlogs button:focus-visible,#atlas-botlogs summary:focus-visible{outline:2px solid var(--ring,#a78bfa);outline-offset:2px}",
    "#atlas-botlogs button[aria-pressed=true]{background:var(--accent);font-weight:600}",
    "#atlas-botlogs .bl-card{border:1px solid var(--border);border-left:4px solid var(--bl-c);border-radius:10px;background:var(--card);padding:12px}",
    "#atlas-botlogs .bl-card.arch{opacity:.82}",
    "#atlas-botlogs .bl-head{display:flex;flex-wrap:wrap;gap:8px;align-items:center}",
    "#atlas-botlogs .bl-goal{flex:1 1 240px;min-width:0;overflow-wrap:anywhere}",
    "#atlas-botlogs .bl-meta{color:var(--muted-foreground);font-size:12px;overflow-wrap:anywhere;min-width:0}",
    "#atlas-botlogs .bl-tag{display:inline-flex;gap:6px;align-items:center;border:1px solid var(--bl-c);color:var(--bl-c);border-radius:999px;padding:2px 10px;font-size:12px;font-weight:600;background:color-mix(in srgb,var(--bl-c) 12%,transparent);max-width:100%;flex-wrap:wrap;text-align:left;overflow-wrap:anywhere}",
    "#atlas-botlogs .bl-tag.lead{border-radius:6px;text-transform:uppercase}",
    "#atlas-botlogs .bl-cat{display:inline-block;border-radius:6px;padding:1px 8px;font-size:11px;font-weight:600;color:#111;background:var(--bl-c)}",
    "#atlas-botlogs .bl-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}",
    "#atlas-botlogs .bl-log{margin-top:10px;border-top:1px solid var(--border);padding-top:8px;display:flex;flex-direction:column;gap:4px;font-size:13px}",
    "#atlas-botlogs .bl-line{overflow-wrap:anywhere}",
    "#atlas-botlogs .bl-line time{font-weight:600;margin-right:6px;font-variant-numeric:tabular-nums}",
    "#atlas-botlogs .bl-line.error{color:#f87171}",
    "#atlas-botlogs .bl-err{margin-top:8px;color:#f87171;overflow-wrap:anywhere}",
    "#atlas-botlogs .bl-empty{color:var(--muted-foreground);text-align:center;padding:40px 0}",
    "#atlas-botlogs .bl-legend{display:flex;flex-wrap:wrap;gap:6px}",
    "#atlas-botlogs .bl-search{background:transparent;border:1px solid var(--border);border-radius:6px;padding:4px 10px;color:inherit;font:inherit;min-width:180px}",
    "#atlas-botlogs .bl-cat-group{margin-top:6px;display:flex;flex-direction:column;gap:8px}",
    "#atlas-botlogs .bl-cat-group>summary{cursor:pointer;display:flex;align-items:center;gap:8px;list-style:disclosure-closed}",
    "#atlas-botlogs .bl-cat-group[open]>summary{list-style:disclosure-open}",
    "@media (max-width:640px){#atlas-botlogs{padding:12px}}",
    "@media (prefers-reduced-motion:reduce){#atlas-botlogs *{transition:none!important;animation:none!important}}"
  ].join("\n");
  document.head.appendChild(css);

  /* ---------- sidebar item ---------- */
  var ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
  function addNavItem() {
    if (document.getElementById("atlas-botlogs-nav")) return;
    var play = document.querySelector('a[data-slot="sidebar-menu-button"][href$="/playground"]');
    var li = play && play.closest('[data-slot="sidebar-menu-item"]');
    if (!li) return;
    var item = li.cloneNode(true);
    item.id = "atlas-botlogs-nav";
    item.querySelectorAll("[id]").forEach(function (el) { el.removeAttribute("id"); });
    var a = item.querySelector('a[data-slot="sidebar-menu-button"]');
    ["id", "aria-describedby", "data-state", "data-active", "aria-current"].forEach(function (k) { a.removeAttribute(k); });
    a.setAttribute("href", ROUTE);
    var svg = a.querySelector("svg"); if (svg) svg.outerHTML = ICON;
    var label = a.querySelector("span"); if (label) { label.className = ""; label.textContent = "Swarm Board"; }
    a.setAttribute("title", "Swarm Board");
    li.parentNode.insertBefore(item, li.nextSibling);
    markActive();
  }
  function markActive() {
    var a = document.querySelector("#atlas-botlogs-nav a");
    if (!a) return;
    if (onPage()) { a.setAttribute("data-active", ""); a.setAttribute("aria-current", "page"); }
    else { a.removeAttribute("data-active"); a.removeAttribute("aria-current"); }
  }

  /* ---------- page ---------- */
  function panel() {
    var p = document.getElementById("atlas-botlogs");
    var inset = document.querySelector('[data-slot="sidebar-inset"]');
    if (!inset) return null;
    if (!p) {
      p = document.createElement("section");
      p.id = "atlas-botlogs"; p.setAttribute("aria-label", "Bot Logs"); p.hidden = true;
      p.addEventListener("click", onClick);
      p.addEventListener("input", onInput);
      p.addEventListener("toggle", onToggle, true);
    }
    if (p.parentNode !== inset) inset.appendChild(p);
    if (getComputedStyle(inset).position === "static") inset.style.position = "relative";
    var header = inset.querySelector("header");
    p.style.top = (header ? header.offsetHeight : 0) + "px";
    return p;
  }
  function setTitle(on) {
    var header = document.querySelector('[data-slot="sidebar-inset"] header');
    if (on) {
      if (view.titleNode || !header) return;
      var w = document.createTreeWalker(header, NodeFilter.SHOW_TEXT);
      for (var n = w.nextNode(); n; n = w.nextNode()) if (n.nodeValue.trim() === "Activity") { view.titleNode = n; view.titleText = n.nodeValue; n.nodeValue = "Swarm Board"; break; }
    } else if (view.titleNode) { view.titleNode.nodeValue = view.titleText; view.titleNode = null; }
  }
  function route() {
    markActive();
    var p = panel(); if (!p) return;
    if (onPage()) {
      p.hidden = false; setTitle(true);
      var r = runParam(); if (r) view.open["run:" + r] = true;
      load();
      if (!view.timer) view.timer = setInterval(function () { if (!document.hidden) load(); }, 3000);
    } else {
      p.hidden = true; setTitle(false);
      clearInterval(view.timer); view.timer = null;
    }
  }
  function load() {
    fetch("/__atlas/bot-logs.json?limit=60&lines=60", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); })
      .then(function (raw) {
        if (raw === view.lastJson && !view.error) return;
        view.lastJson = raw;
        view.data = JSON.parse(raw);
        view.error = "";
        render();
      })
      .catch(function (e) { view.error = "Could not read bot logs from Atlas: " + e.message; render(); });
  }

  function tag(chat, lead, runId) {
    var s = STATE[chat.state] || STATE.queued, key = "chat:" + chat.conversation_id;
    return '<button type="button" class="bl-tag' + (lead ? " lead" : "") + '" style="--bl-c:' + s.c + '" data-toggle="' + esc(key) + '" aria-expanded="' + (!!view.open[key]) + '" title="' + esc(chat.task || chat.bot) + '">'
      + '<span aria-hidden="true">' + s.m + "</span>" + esc(lead ? "Swarm Lead" : chat.bot.replace(/^10x:\s*/i, "")) + " · " + s.w
      + '<span class="bl-meta" style="color:inherit;font-weight:400">' + dur(chat.seconds) + "</span></button>";
  }
  function logBlock(chat) {
    var lines = (chat.lines || []).map(function (l) {
      return '<div class="bl-line ' + (l.level === "error" ? "error" : "") + '"><time>' + clock(l.ts) + "</time>" + (l.level === "error" ? "(problem) " : "") + esc(l.message) + "</div>";
    }).join("");
    return '<div class="bl-log" aria-label="' + esc(chat.bot) + ' log"><div class="bl-meta">' + esc(chat.bot) + " · " + esc(chat.task) + " · attempts " + chat.attempts + "</div>"
      + (lines || '<div class="bl-meta">No log lines yet.</div>') + "</div>";
  }
  function card(run) {
    var s = STATE[run.state] || STATE.queued, cat = CATEGORY[run.category] || CATEGORY.other;
    var color = run.archived ? cat.c : s.c, key = "run:" + run.run_id;
    var lead = run.lead ? tag(run.lead, true, run.run_id) : '<span class="bl-tag lead" style="--bl-c:' + s.c + '">' + s.m + " Run · " + s.w + "</span>";
    var bots = run.chats.map(function (c) { return tag(c, false, run.run_id); }).join("");
    var opened = run.chats.concat(run.lead ? [run.lead] : []).filter(function (c) { return view.open["chat:" + c.conversation_id]; }).map(logBlock).join("");
    var errs = run.chats.concat(run.lead ? [run.lead] : []).filter(function (c) { return c.error; });
    var done = run.chats.filter(function (c) { return c.state === "done"; }).length;
    return '<article class="bl-card' + (run.archived ? " arch" : "") + '" style="--bl-c:' + color + '" aria-label="Swarm run ' + esc(run.goal || run.run_id) + '">'
      + '<div class="bl-head">' + lead
      + (run.archived ? '<span class="bl-cat" style="--bl-c:' + cat.c + '">' + cat.w + " · archived</span>" : "")
      + '<span class="bl-goal">' + esc(run.goal || "(no goal saved)") + "</span>"
      + '<span class="bl-meta">' + clock(run.started) + " · bots " + done + "/" + run.chats.length + " · " + esc(run.run_id) + "</span>"
      + '<button type="button" data-open-run="' + esc(run.run_id) + '" data-conv="' + esc(run.lead ? run.lead.conversation_id : (run.chats[0] ? run.chats[0].conversation_id : "")) + '">Open Chat</button>'
      + '<button type="button" data-archive-run="' + esc(run.run_id) + '" aria-pressed="' + (!!run.archived) + '">' + (run.archived ? "Unarchive" : "Archive") + "</button>"
      + '<button type="button" data-toggle="' + esc(key) + '" aria-expanded="' + (!!view.open[key]) + '">' + (view.open[key] ? "Hide all logs" : "Show all logs") + "</button></div>"
      + '<div class="bl-tags">' + bots + "</div>"
      + (!view.open[key] && errs.length ? '<div class="bl-err">' + esc(errs[0].bot + ": " + errs[0].error) + "</div>" : "")
      + (view.open[key] ? run.chats.concat(run.lead ? [run.lead] : []).map(logBlock).join("") : opened)
      + "</article>";
  }
  function matchesRun(r, q) {
    if (!q) return true;
    var hay = [r.goal, r.run_id, r.state, r.category].concat((r.chats || []).map(function (c) { return (c.bot || "") + " " + (c.task || ""); })).join(" ").toLowerCase();
    return hay.indexOf(q) >= 0;
  }
  function render() {
    var p = document.getElementById("atlas-botlogs"); if (!p || p.hidden) return;
    var allRuns = (view.data && view.data.runs) || [];
    var q = view.query.trim().toLowerCase();
    var runs = q ? allRuns.filter(function (r) { return matchesRun(r, q); }) : allRuns;
    var live = runs.filter(function (r) { return !r.archived; });
    var problems = runs.filter(function (r) { return ["failed", "timeout", "stalled"].indexOf(r.state) >= 0; });
    var arch = runs.filter(function (r) { return r.archived; });
    var f = view.filter;
    var filters = [["all", "All", runs.length], ["live", "Live and open", live.length], ["problems", "Problems", problems.length], ["archive", "Archive", arch.length]]
      .map(function (x) { return '<button type="button" data-filter="' + x[0] + '" aria-pressed="' + (f === x[0]) + '">' + x[1] + " (" + x[2] + ")</button>"; }).join("");
    var legend = Object.keys(STATE).map(function (k) { var s = STATE[k]; return '<span class="bl-tag" style="--bl-c:' + s.c + '">' + s.m + " " + s.w + "</span>"; }).join("");
    var body = "";
    if (view.error) body += '<div class="bl-err" role="alert">' + esc(view.error) + "</div>";
    if (f !== "archive") {
      var list = f === "problems" ? problems : live;
      body += "<h3>" + (f === "problems" ? "Problems" : "Live and open runs") + "</h3>";
      body += list.length ? list.map(card).join("") : '<div class="bl-empty">No runs here.</div>';
    }
    if (f === "all" || f === "archive") {
      body += "<h3>Archive</h3>";
      if (!arch.length) body += '<div class="bl-empty">Finished runs appear here, sorted by category.</div>';
      var shownCats = 0;
      Object.keys(CATEGORY).forEach(function (k) {
        var group = arch.filter(function (r) { return r.category === k; });
        if (!group.length) return;
        var isOpen = q ? true : (k in view.catOpen ? view.catOpen[k] : shownCats === 0);
        shownCats++;
        body += '<details class="bl-cat-group" data-cat="' + esc(k) + '"' + (isOpen ? " open" : "") + '><summary class="bl-meta"><span class="bl-cat" style="--bl-c:' + CATEGORY[k].c + '">' + CATEGORY[k].w + "</span> " + group.length + " finished</summary>" + group.map(card).join("") + "</details>";
      });
    }
    var scroll = p.scrollTop;
    var active = document.activeElement, keepSearch = active && active.classList && active.classList.contains("bl-search");
    var selStart = keepSearch ? active.selectionStart : null, selEnd = keepSearch ? active.selectionEnd : null;
    p.innerHTML = '<div class="bl-wrap"><div class="bl-top"><h2>Swarm Board</h2><input type="search" class="bl-search" aria-label="Search swarm board" placeholder="Search runs…" value="' + esc(view.query) + '"><div class="bl-top" role="group" aria-label="Filter runs">' + filters + "</div>"
      + '<button type="button" data-refresh>Refresh</button></div><div class="bl-legend" aria-label="State colours">' + legend + "</div>" + body + "</div>";
    p.scrollTop = scroll;
    if (keepSearch) { var inp = p.querySelector(".bl-search"); if (inp) { inp.focus(); if (selStart !== null) inp.setSelectionRange(selStart, selEnd); } }
  }
  function onInput(e) {
    if (!e.target || !e.target.classList || !e.target.classList.contains("bl-search")) return;
    view.query = e.target.value;
    clearTimeout(view.searchTimer);
    view.searchTimer = setTimeout(render, 120);
  }
  function onToggle(e) {
    var d = e.target;
    if (d && d.dataset && d.dataset.cat) view.catOpen[d.dataset.cat] = d.open;
  }
  function toggleRunArchive(runId) {
    var runs = (view.data && view.data.runs) || [];
    var run = runs.find(function (r) { return r.run_id === runId; });
    if (!run) return;
    var next = !run.archived;
    run.archived = next;
    view.lastJson = "";
    render();
    fetch("/api/ops/swarm/runs/" + encodeURIComponent(runId) + "/archive", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ archived: next })
    }).catch(function () {});
  }
  function onClick(e) {
    var t = e.target.closest("button"); if (!t) return;
    if (t.dataset.filter) { view.filter = t.dataset.filter; render(); }
    else if (t.dataset.openRun) {
      var msg = { type: "atlas:open-chat", run_id: t.dataset.openRun, conversation_id: t.dataset.conv || "" };
      try { if (window.parent && window.parent !== window) window.parent.postMessage(msg, "*"); } catch (_) {}
      try { if (window.top && window.top !== window && window.top !== window.parent) window.top.postMessage(msg, "*"); } catch (_) {}
    }
    else if (t.dataset.archiveRun) { toggleRunArchive(t.dataset.archiveRun); }
    else if (t.dataset.toggle) { view.open[t.dataset.toggle] = !view.open[t.dataset.toggle]; render(); }
    else if (t.hasAttribute("data-refresh")) load();
  }

  window.addEventListener("hashchange", route);
  new MutationObserver(function () { addNavItem(); if (onPage()) panel(); }).observe(document.documentElement, { childList: true, subtree: true });
  addNavItem(); route();
})();
