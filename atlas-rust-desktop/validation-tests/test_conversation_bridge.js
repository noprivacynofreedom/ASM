
import fs from 'node:fs';
// Defaults resolve from this file, so the test works from any folder and reads the shipped files.
const at = rel => new URL('../' + rel, import.meta.url);
const app = fs.readFileSync(process.argv[2] || at('src/App.tsx'), 'utf8');
const html = fs.readFileSync(process.argv[3] || at('src-tauri/resources/atlas/index.html'), 'utf8');
const server = fs.readFileSync(process.argv[4] || at('src-tauri/resources/atlas/server.py'), 'utf8');
const rust = fs.readFileSync(process.argv[5] || at('src-tauri/src/main.rs'), 'utf8');
const audit = fs.readFileSync(process.argv[6] || at('src-tauri/resources/atlas/mcp_audit.py'), 'utf8');
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
  // The tagging moved from server.py into mcp_audit.MCPAuditRecorder.
  ['MCP records are tagged with conversation identity', /from mcp_audit import MCPAuditRecorder/.test(server) && /row\["conversation_id"\] = str\(conversation_id or ""\)/.test(audit)],
];
let failed=0;
for(const [name,ok] of checks){console.log(`${ok?'PASS':'FAIL'} ${name}`);if(!ok)failed++;}
process.exit(failed?1:0);
