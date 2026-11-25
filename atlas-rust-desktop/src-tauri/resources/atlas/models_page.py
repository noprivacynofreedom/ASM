"""Self-contained page for /models: pick the .gguf file for each model name, and see where reply time went.
The page itself never scrolls (CLAUDE.md section 8): only #scroll does."""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Models</title>
<style>
:root{color-scheme:dark;--bg:#14101c;--panel:#1d1729;--line:#493660;--text:#ece6f5;--muted:#a99bc0;--ok:#6fd49a;--bad:#ff8a8a;--accent:#c99bff}
@media (prefers-color-scheme:light){:root{color-scheme:light;--bg:#f6f2fb;--panel:#fff;--line:#c9b8e0;--text:#231a33;--muted:#5d4f75;--ok:#14733f;--bad:#a02020;--accent:#6a2fb0}}
*{box-sizing:border-box}html,body{height:100%;margin:0;overflow:hidden}
body{display:flex;flex-direction:column;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,sans-serif}
header{flex:none;padding:12px 16px;border-bottom:1px solid var(--line)}
#scroll{flex:1;min-height:0;overflow:auto;padding:16px}
h1{font-size:18px;margin:0}h2{font-size:15px;margin:0 0 8px}p{margin:4px 0 10px;color:var(--muted)}
a{color:var(--accent)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px;margin:0 0 14px;max-width:900px}
.row{display:grid;grid-template-columns:110px 1fr;gap:8px;align-items:center;margin:0 0 10px}
@media (max-width:520px){.row{grid-template-columns:1fr}}
select{width:100%;padding:8px;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:4px;font:inherit}
button{padding:8px 14px;margin:0 8px 0 0;background:var(--panel);color:var(--text);border:1px solid var(--accent);border-radius:4px;font:inherit;cursor:pointer}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
#status{min-height:1.5em;font-weight:600}.ok{color:var(--ok)}.bad{color:var(--bad)}
table{border-collapse:collapse;width:100%;font-size:12px}th,td{border-top:1px solid var(--line);padding:4px 6px;text-align:left;white-space:nowrap}
.tw{overflow-x:auto}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body>
<header><h1>Models</h1><p><a href="/">&larr; Back to chat</a></p></header>
<div id="scroll"><main>
<section class="card" aria-labelledby="h-map">
<h2 id="h-map">Model files</h2>
<p id="dirs">Looking for .gguf files...</p>
<form id="form"></form>
<p><button type="button" id="save">Save</button><button type="button" id="reset">Use automatic choice</button></p>
<div id="status" role="status" aria-live="polite"></div>
<p>After you save, close Atlas and start it again. Atlas rewrites the llama-swap config at start. A model name that you leave on "automatic" keeps the tuned setting.</p>
</section>
<section class="card" aria-labelledby="h-t">
<h2 id="h-t">Last replies (time check)</h2>
<p>wait = seconds before llama.cpp began to read the prompt (model load, model swap, or another request on the same slot). cache = prompt tokens re-used from the cache. The last column shows how big each prompt part is (4 chars = about 1 token): system text, chat history, tool list.</p>
<div class="tw"><table><thead><tr><th>request</th><th>#</th><th>model</th><th>loaded</th><th>prompt</th><th>cache</th><th>tok/s</th><th>wait s</th><th>first token s</th><th>total s</th><th>end</th><th>sys / chat / tools (k chars)</th></tr></thead><tbody id="t"></tbody></table></div>
</section></main></div>
<script>
const ALIASES=["coder","mentor","tasks","assist","reviewer","vision"];
const $=s=>document.querySelector(s);let state={};
function say(t,c){const e=$("#status");e.textContent=t;e.className=c||""}
async function load(){
  const r=await fetch("/api/models/local");state=await r.json();
  $("#dirs").textContent=state.files.length?("Folders searched: "+state.dirs.join(", ")):"No .gguf files found. Put them in a models folder, or set ATLAS_MODELS_DIR.";
  const f=$("#form");f.textContent="";
  for(const a of ALIASES){
    const row=document.createElement("div");row.className="row";
    const lab=document.createElement("label");lab.htmlFor="m-"+a;lab.textContent=a;
    const sel=document.createElement("select");sel.id="m-"+a;
    const auto=new Option("automatic (current: "+(state.current[a]||"none")+")","");sel.add(auto);
    for(const m of state.files){sel.add(new Option(m.name+"  ("+m.gb+" GB)",m.path))}
    sel.value=state.overrides[a]||"";
    row.append(lab,sel);f.append(row);
  }
  const tr=await (await fetch("/api/chat-timing")).json();
  const tb=$("#t");tb.textContent="";
  for(const x of tr.rows){const r=document.createElement("tr");
    for(const v of [String(x.request_id).slice(-6),x.n,x.model,x.loaded_before,x.prompt_n,x.cache_n,x.prompt_per_second,x.wait_s,x.ttft_s,x.total_s,x.finish||"ok",(x.prompt_chars?[x.prompt_chars.system,x.prompt_chars.history,x.prompt_chars.tools].map(n=>Math.round((n||0)/1000)).join(" / "):"")]){
      const td=document.createElement("td");td.textContent=v==null?"-":v;r.append(td)}
    tb.append(r)}
}
async function save(map){
  const r=await fetch("/api/models/map",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({map})});
  const j=await r.json();
  if(j.ok){say("Saved. Close Atlas and start it again to use the new files.","ok")}else{say(j.error||"Could not save","bad")}
}
$("#save").onclick=()=>{const map={};for(const a of ALIASES){const v=$("#m-"+a).value;if(v)map[a]=v}save(map)};
$("#reset").onclick=async()=>{await save({});load()};
load().catch(e=>say("Could not load: "+e,"bad"));
</script></body></html>
"""
