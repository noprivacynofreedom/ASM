const { chromium } = require('playwright');
(async () => {
  const bot = { id: 'b1', name: 'Overseer P', model: 'coder', system: 'You are helpful.', temperature: 0.3, top_p: 0.9, max_tokens: 512 };
  await fetch('http://127.0.0.1:18090/api/state', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ bots: [bot], chats: [], activeBot: 'b1' }) });
  const br = await chromium.launch(); const pg = await br.newPage({ viewport: { width: 1400, height: 900 } });
  await pg.goto('http://127.0.0.1:18090/'); await pg.waitForTimeout(1500);
  await pg.fill('#input', 'test'); await pg.press('#input', 'Enter');
  await pg.waitForFunction(() => document.querySelectorAll('#log .stats').length > 0, null, { timeout: 60000 });
  const msgs = await pg.$$eval('#log .msg, #log > div', els => els.map(e => e.innerText.replace(/\s+/g,' ').slice(0,160)).slice(-4));
  const head = await pg.evaluate(() => { const h = document.querySelector('.head'); return h ? [h.scrollHeight, h.clientHeight] : null; });
  console.log(JSON.stringify({ last: msgs.slice(-2), headScrollClient: head }));
  await br.close();
})().catch(e => { console.log('FAIL', e.message.split('\n')[0]); process.exit(1); });
