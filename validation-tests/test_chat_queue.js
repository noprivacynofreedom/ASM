const fs=require("fs");
const html=fs.readFileSync(process.argv[2]||"index.html","utf8");
const checks=[
 ["queue persists in app state",/queue:\s*\[\]/.test(html)&&/queue:\s*Array\.isArray\(d\.queue\)/.test(html)],
 ["messages enqueue during generation",/if\(ctrl\|\|queueRunning\|\|queueDrainPromise\)\{\s*enqueueMessage\(t\)/.test(html)],
 ["queue captures chat, bot and attachments",/attachments,chatId:S\.chat,botId:S\.bot/.test(html)],
 ["queue processes sequentially",/while\(!ctrl&&!S\.queuePaused&&S\.queue\.length\)/.test(html)&&/await send\(job\.text/.test(html)],
 ["queue pause state persists",/queuePaused:\s*!!d\.queuePaused/.test(html)],
 ["pause and resume controls exist",/id="queuePause"/.test(html)&&/\$\("#queuePause"\)\.onclick/.test(html)],
 ["send next processes one item",/drainQueue\(true\)/.test(html)&&/if\(single\)\{S\.queuePaused=true/.test(html)],
 ["queued messages can be edited",/data-queue-edit/.test(html)&&/prompt\("Edit queued message:"/.test(html)],
 ["queued messages can be held",/data-queue-hold/.test(html)&&/job\.hold=!job\.hold/.test(html)],
 ["queued messages can be reordered",/data-queue-up/.test(html)&&/data-queue-down/.test(html)],
 ["active message is protected from mutation",/if\(queueRunning&&jobId===q\[0\]\?\.id\)return/.test(html)],
 ["queue remains bounded",/length>=20/.test(html)],
 ["queued image payload remains bounded",/imageBytes>8\*1024\*1024/.test(html)]
];
let failed=0;for(const [n,ok] of checks){console.log(`${ok?"PASS":"FAIL"} ${n}`);if(!ok)failed++;}
process.exit(failed?1:0);
