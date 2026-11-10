import fs from 'node:fs';
import assert from 'node:assert/strict';

const html = fs.readFileSync(process.argv[2] || 'index.html', 'utf8');
const app = fs.readFileSync(process.argv[3] || 'atlas-rust-desktop/src/App.tsx', 'utf8');
const tests = [];
function check(name, fn) { try { fn(); console.log(`PASS ${name}`); } catch (error) { console.log(`FAIL ${name}: ${error.message}`); tests.push(name); } }

check('unknown image capability asks before chat mutation', () => {
  const send = html.slice(html.indexOf('async function send(text, options={}){'), html.indexOf('/* ---------- bot editor ----------'));
  assert.ok(send.indexOf('confirm(`Image support is not verified') < send.indexOf('let c = chat() || newChat()'));
  assert.ok(send.indexOf('confirm(`Image support is not verified') < send.indexOf('if(!options.attachments)$("#input").value=""'));
  assert.match(send, /support==="text-only"\).*return "ERROR"/);
  assert.match(html, /imageSupport: \$\("#fImageSupport"\)\.value/);
});

check('model change resets image capability to unknown', () => {
  assert.match(html, /if\(bot\(\)\.model!==e\.target\.value\)bot\(\)\.imageSupport="unknown"/);
  assert.match(html, /\$\("#fModel"\)\.addEventListener\("change",\(\)=>\{ \$\("#fImageSupport"\)\.value="unknown"/);
});

check('voice settings disclose service handling and never auto-send', () => {
  assert.match(html, /Speech recognition support depends on this browser or Windows WebView/);
  assert.match(html, /Dictation only inserts text into the message box\. It never sends messages/);
  assert.match(html, /recognition\.lang=voiceSettings\.language/);
  assert.match(html, /recognition\.continuous=!!voiceSettings\.continuous/);
  assert.match(html, /atlasVoiceDisclosureAccepted/);
});

check('activity feed uses redacted activity route and filters', () => {
  const fn = html.slice(html.indexOf('async function refreshActivityEvents()'), html.indexOf('function syncActivityCompanion()'));
  assert.match(fn, /\/activity\?after=\$\{activityCursor\}&limit=100/);
  assert.doesNotMatch(fn, /e\.(?:message|details|result|error|payload)/);
  assert.match(html, /id="activityFilter"/);
  assert.match(html, /\["Idle","Thinking","Tool","Task","Needs attention","Done","Failed"\]/);
});

check('right-click keeps selected text and edit controls usable', () => {
  assert.match(html, /if\(selected\|\|e\.target\.closest\("input,textarea,select,\[contenteditable='true'\]"\)\)return/);
  assert.match(app, /if\(selected\|\|target\?\.closest\('input,textarea,select,\[contenteditable="true"\]'\)\)return/);
  assert.match(html, /copy-message[^\n]*user-select:none/);
});

check('benchmark labels generation and total-request estimates separately', () => {
  assert.match(app, /tokens_per_second_kind==='generation_only'\?'GENERATION RATE'/);
  assert.match(app, /tokens_per_second_kind==='total_request_estimate'\?'END-TO-END ESTIMATE'/);
  assert.match(app, /prompt_eval_duration_ns/);
  assert.match(app, /eval_duration_ns/);
});

if (tests.length) process.exit(1);
