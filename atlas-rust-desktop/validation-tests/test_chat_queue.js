
import fs from 'node:fs';
const html = fs.readFileSync(process.argv[2] || "index.html", "utf8");
const checks = [
  ["queue state persists with app state", /queue:\s*\[\]/.test(html) && /queue:\s*Array\.isArray\(d\.queue\)/.test(html)],
  ["submissions during generation or drain are queued", /if\(ctrl\|\|queueRunning\|\|queueDrainPromise\)\{\s*enqueueMessage\(t\)/.test(html)],
  ["queue captures conversation, bot and attachments", /attachments,chatId:S\.chat,botId:S\.bot/.test(html)],
  ["queue drains sequentially with single-flight lock", /queueDrainPromise=Promise\.resolve\(\)\.then\(async\(\)=>/.test(html) && /await send\(job\.text/.test(html)],
  ["queue retains failed or cancelled item", /outcome!=="DONE"[\s\S]{0,220}MESSAGE RETAINED/.test(html)],
  ["queue removes completed job by stable ID", /findIndex\(item=>item\.id===job\.id\)/.test(html)],
  ["queue items can be removed and reordered", /data-queue-remove/.test(html) && /data-queue-up/.test(html)],
  ["queue bounded to 20 messages", /length>=20/.test(html)],
  ["queue image payload bounded", /imageBytes>8\*1024\*1024/.test(html)],
  ["conversation link posts a versioned parent message", /type:"atlas:open-conversation", version:1/.test(html)],
  ["chat requests carry conversation and bot identity", /_atlas_context:\{conversation_id:c\.id,bot_id:b\.id/.test(html)]
];
let failed = 0;
for (const [name, ok] of checks) { console.log(`${ok ? "PASS" : "FAIL"} ${name}`); if (!ok) failed++; }
process.exit(failed ? 1 : 0);
