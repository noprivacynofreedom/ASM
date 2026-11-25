const { chromium } = require('playwright');
const mode = process.argv[2];  // close | stop
(async () => {
  const bot = { id: 'b1', name: 'Overseer P', model: 'coder', system: 'x', temperature: 0.3, top_p: 0.9, max_tokens: 512 };
  await fetch('http://127.0.0.1:18090/api/state', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ bots: [bot], chats: [] }) });
  const br = await chromium.launch(); const pg = await br.newPage({ viewport: { width: 1400, height: 900 } });
  await pg.goto('http://127.0.0.1:18090/'); await pg.waitForTimeout(1500);
  await pg.fill('#input', 'test'); await pg.press('#input', 'Enter'); await pg.waitForTimeout(2500);
  if (mode === 'stop') { await pg.click('#stop'); await pg.waitForTimeout(500); }
  // make sure the page saved the chat (with the user message) before it goes away
  await pg.waitForTimeout(1200);
  await br.close();   // window gone
  await new Promise(r => setTimeout(r, 12000));
  const st = await (await fetch('http://127.0.0.1:18090/api/state')).json();
  const msgs = ((st.chats || [])[0] || {}).messages || [];
  console.log(mode, JSON.stringify(msgs.map(m => [m.role, String(m.content).slice(0, 60), !!m.detached])));
})();
