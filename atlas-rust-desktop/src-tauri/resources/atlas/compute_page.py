"""Self-contained page for /compute: add a laptop, test it, see which models it has."""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Compute sharing</title>
<style>
:root{color-scheme:dark;--bg:#14101c;--panel:#1d1729;--line:#493660;--text:#ece6f5;--muted:#a99bc0;--ok:#6fd49a;--bad:#ff8a8a;--accent:#c99bff}
@media (prefers-color-scheme:light){:root{color-scheme:light;--bg:#f6f2fb;--panel:#fff;--line:#c9b8e0;--text:#231a33;--muted:#5d4f75;--ok:#14733f;--bad:#a02020;--accent:#6a2fb0}}
*{box-sizing:border-box}body{margin:0;padding:16px;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,sans-serif}
h1{font-size:18px;margin:0 0 4px}p{margin:0 0 12px;color:var(--muted)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px;margin:0 0 14px;max-width:760px}
label{display:block;margin:0 0 10px;font-weight:600}label span{display:block;font-weight:400;color:var(--muted);font-size:12px}
input{width:100%;padding:8px;margin-top:4px;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:4px;font:inherit}
button{padding:8px 14px;margin:0 8px 0 0;background:var(--panel);color:var(--text);border:1px solid var(--accent);border-radius:4px;font:inherit;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
#status{min-height:1.5em;margin-top:10px;font-weight:600}.ok{color:var(--ok)}.bad{color:var(--bad)}
.peer{border-top:1px solid var(--line);padding:10px 0}.peer:first-child{border-top:0}
.chip{display:inline-block;padding:1px 8px;margin:2px 4px 2px 0;border:1px solid var(--line);border-radius:10px;font-size:12px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style></head><body>
<h1>Compute sharing</h1>
<p>Send whole models to another machine on your home network. One request goes to one machine. Models are never split.</p>
<form class="card" id="form" autocomplete="off">
  <label>Machine name<input id="name" value="Laptop" maxlength="40"></label>
  <label>Laptop URL<span>Example: http://192.168.1.50:8080. Home-network addresses only.</span><input id="url" inputmode="url" placeholder="http://192.168.1.50:8080"></label>
  <label>Models to send to this machine<span>Comma separated aliases. Leave empty to use every model the machine reports.</span><input id="models" placeholder="laptop-7b, laptop-14b"></label>
  <button type="button" id="test">Test connection</button><button type="submit" id="save">Save machine</button>
  <div id="status" role="status" aria-live="polite"></div>
</form>
<section class="card" aria-labelledby="saved"><h2 id="saved" style="font-size:15px;margin:0 0 8px">Saved machines</h2><div id="peers">Loading...</div></section>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function say(text,ok){const s=$('status');s.textContent=text;s.className=ok===true?'ok':ok===false?'bad':'';}
const list=()=>$('models').value.split(',').map(x=>x.trim()).filter(Boolean);
async function post(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return r.json();}
async function load(){
  try{
    const d=await (await fetch('/api/compute/peers')).json();
    const rows=(d.peers||[]).map(p=>`<div class="peer"><strong>${esc(p.name)}</strong> <span class="${p.online?'ok':'bad'}">${esc(p.message)}</span>${p.latency_ms!=null?` <small>(${p.latency_ms} ms)</small>`:''}<br>
      <small>${esc(p.url)}</small><br>Routed to this machine: ${(p.routed_models||[]).map(m=>`<span class="chip">${esc(m)}</span>`).join('')||'<small>none</small>'}<br>
      <button type="button" data-remove="${esc(p.name)}">Remove ${esc(p.name)}</button></div>`);
    const problems=(d.problems||[]).map(x=>`<p class="bad">${esc(x)}</p>`).join('');
    $('peers').innerHTML=(rows.join('')||'<p>No other machine saved yet.</p>')+problems;
  }catch(e){$('peers').textContent='Cannot read the machine list: '+e.message;}
}
$('test').onclick=async()=>{
  $('test').disabled=true;say('Testing...');
  try{const d=await post('/api/compute/peers/test',{url:$('url').value,name:$('name').value});
    say(d.message||d.error||'No answer.',!!d.online);
    if(d.online&&d.models&&d.models.length&&!$('models').value)$('models').placeholder=d.models.join(', ');
  }catch(e){say('Test failed: '+e.message,false);}finally{$('test').disabled=false;}
};
$('form').onsubmit=async e=>{
  e.preventDefault();$('save').disabled=true;say('Saving...');
  try{const d=await post('/api/compute/peers',{name:$('name').value,url:$('url').value,models:list()});
    if(!d.ok)throw new Error(d.error||'Save failed');
    say(`Saved ${d.name}. Models sent there: ${(d.models||[]).join(', ')||'none yet'}.`,true);await load();
  }catch(err){say(err.message,false);}finally{$('save').disabled=false;}
};
$('peers').onclick=async e=>{
  const name=e.target.dataset&&e.target.dataset.remove;if(!name)return;
  await post('/api/compute/peers/remove',{name});say(`Removed ${name}.`,true);await load();
};
load();setInterval(load,15000);
</script></body></html>"""
