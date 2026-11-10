
import fs from 'node:fs';
const app = fs.readFileSync(process.argv[2] || 'src/App.tsx', 'utf8');
const html = fs.readFileSync(process.argv[3] || '../index.html', 'utf8');
const server = fs.readFileSync(process.argv[4] || '../server.py', 'utf8');
const rust = fs.readFileSync(process.argv[5] || 'src-tauri/src/main.rs', 'utf8');
const checks = [
  ['chat iframe remains mounted outside view conditional', /<iframe ref=\{chatFrameRef\}[^>]*style=\{\{display:view==='chat'\?'block':'none'\}\}/.test(app)],
  ['message source is validated against the mounted iframe', /event\.source!==frame\?\.contentWindow/.test(app)],
  ['message origin is restricted to local Atlas chat', /event\.origin!=='http:\/\/127\.0\.0\.1:8090'/.test(app)],
  ['conversation messages are validated before navigation', /data\.type!=='atlas:open-conversation'[\s\S]{0,220}setSelectedConversationId\(id\)[\s\S]{0,80}setView\('ops'\)/.test(app)],
  ['Operations receives selected conversation ID', /<OperationsDashboard selectedConversationId=\{selectedConversationId\}/.test(app)],
  ['desktop invokes conversation diagnostics command', /invoke<ConversationDiagnostics>\('ops_conversation_diagnostics'/.test(app)],
  ['Rust exposes the diagnostics invoke command', /async fn ops_conversation_diagnostics/.test(rust) && /ops_conversation_diagnostics/.test(rust.slice(rust.indexOf('generate_handler!')))],
  ['chat UI emits the expected versioned message', /type:"atlas:open-conversation", version:1/.test(html)],
  ['chat request carries conversation and bot identity', /_atlas_context:\{conversation_id:c\.id,bot_id:b\.id/.test(html)],
  ['Python removes private metadata before upstream proxy', /request_meta\.pop\("_atlas_context", \{\}\)/.test(server)],
  ['Python provides conversation diagnostics endpoint', /api\/ops\/conversations\//.test(server)],
  ['MCP records are tagged with conversation identity', /'conversation_id': conversation_id or None/.test(server)],
];
let failed=0;
for(const [name,ok] of checks){console.log(`${ok?'PASS':'FAIL'} ${name}`);if(!ok)failed++;}
process.exit(failed?1:0);
