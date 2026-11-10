import fs from 'node:fs';
const source = fs.readFileSync(process.argv[2] || 'index.html', 'utf8');
const start = source.indexOf('async function drainQueue(single=false){');
const end = source.indexOf('\nconst bot =', start);
if (start < 0 || end < 0) throw new Error('Could not locate drainQueue implementation');
const drainSource = source.slice(start, end);
function harness(queue, send) {
  const S = { queue, queuePaused: false, chats: [], bots: [], chat: null, bot: null };
  const create = new Function('S','ctrl','send','save','renderAll','renderQueue','setStatus',
    `let queueRunning=false, queueDrainPromise=null;\n${drainSource}\nreturn { run: drainQueue, inspect: () => ({queueRunning, queueDrainPromise}) };`);
  const wrappedSend=(text,options)=>send(text,S,options);
  const runtime=create(S, null, wrappedSend, () => {}, () => {}, () => {}, () => {});
  runtime.state=S;
  return runtime;
}
(async () => {
  let order = [];
  let h = harness([{id:'1',text:'a'},{id:'2',text:'b'},{id:'3',text:'c'}], async text => { order.push(text); return 'DONE'; });
  await h.run();
  if (order.join('') !== 'abc') throw new Error(`Sequential drain failed: ${order}`);
  if (h.inspect().queueDrainPromise !== null || h.inspect().queueRunning) throw new Error('Drain lock was not released after success');

  let attempts = 0;
  h = harness([{id:'bad',text:'bad'},{id:'later',text:'later'}], async () => { attempts++; return 'ERROR'; });
  await h.run();
  if (attempts !== 1) throw new Error('Failed item was retried in a tight loop');
  if (h.inspect().queueDrainPromise !== null || h.inspect().queueRunning) throw new Error('Drain lock was not released after failure');

  h = harness([{id:'held',text:'held',hold:true}], async () => { throw new Error('Held item must not execute'); });
  await h.run();
  if (h.inspect().queueDrainPromise !== null || h.inspect().queueRunning) throw new Error('Held queue left a stale drain lock');

  order = [];
  h = harness([{id:'1',text:'a'},{id:'2',text:'b'}], async text => { order.push(text); return 'DONE'; });
  await h.run(true);
  if (order.join('') !== 'a') throw new Error(`Send-next should process exactly one item: ${order}`);
  order = [];
  h = harness([
    {id:'active',text:'a'},{id:'remove-me',text:'b'},
    {id:'c',text:'c'},{id:'d',text:'d'}
  ], async (text,S) => {
    order.push(text);
    if(text==='a'){
      S.queue.splice(S.queue.findIndex(item=>item.id==='remove-me'),1);
      const c=S.queue.findIndex(item=>item.id==='c');
      const d=S.queue.findIndex(item=>item.id==='d');
      [S.queue[c],S.queue[d]]=[S.queue[d],S.queue[c]];
    }
    return 'DONE';
  });
  await h.run();
  if(order.join('')!=='adc') throw new Error(`Queue mutations during active send were not honoured: ${order}`);

  console.log('PASS drains multiple messages in order');
  console.log('PASS failure retains head item without retry loop');
  console.log('PASS held item releases drain lock');
  console.log('PASS send-next processes one item');
  console.log('PASS removal and reordering during active generation affect the next send');
  console.log('PASS drain lock released on all tested paths');
})().catch(e => { console.error(e); process.exit(1); });
