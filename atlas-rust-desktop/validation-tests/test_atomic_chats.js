// Run with: node tests/test_atomic_chats.js
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync(require('path').join(__dirname, '..', 'index.html'), 'utf8');
const start = html.indexOf('const ATOMIC_STOP =');
const end = html.indexOf('function atomicTransition(previous,next){', start);
assert(start >= 0 && end > start, 'Atomic Chats implementation exists in index.html');
const checks = String.raw`
const parent={id:'parent-1',title:'MCP server timeout',messages:[
 {role:'user',content:'Fix MCP stdio monitor timeout in mcp_monitor.py and inspect tool discovery'},
 {role:'assistant',content:'The reader loop blocks on stdout.readline; use a nonblocking queue and add a timeout test.'},
 {role:'user',content:'MCP tool discovery still hangs when the subprocess exits.'}
]};
const different=atomicShiftAssessment('The CSS grid layout overflows on mobile in dashboard.css',parent);
const same=atomicShiftAssessment('The MCP monitor timeout still blocks the reader thread in mcp_monitor.py',parent);
const capsule=atomicCapsule(parent,'Fix the CSS grid layout');
assert.strictEqual(different.split,true,'a distinct technical area should create an atomic chat');
assert.strictEqual(same.split,false,'a related bug in the same file should stay in its current chat');
assert(capsule.includes('Parent workstream: MCP server timeout'),'capsule identifies parent chat');
assert(capsule.includes('mcp_monitor.py'),'capsule carries file references');
assert.strictEqual(atomicTopicTitle('Fix the CSS grid layout on mobile in dashboard.css'),'Fix the CSS grid layout on mobile in dashboard');
`;
vm.runInNewContext(html.slice(start, end) + checks, { assert, ctrl: null, Date });
console.log('Atomic Chats checks passed: topic split, same-workstream continuation, capsule provenance, title generation.');
