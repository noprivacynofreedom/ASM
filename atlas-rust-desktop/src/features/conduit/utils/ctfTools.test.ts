import test from 'node:test';
import assert from 'node:assert/strict';
import {
  evaluateStackFrame,
  findCyclicOffset,
  generateCyclicPattern,
  packAddress,
  rot13,
} from './ctfTools';

test('cyclic pattern generator locates exact 0x6161616b little-endian offset at byte 40', () => {
  const pattern = generateCyclicPattern(128);
  assert.equal(pattern.length, 128);

  const match = findCyclicOffset(pattern, '0x6161616b', 'little');
  assert.ok(match);
  assert.equal(match.decodedAscii, 'kaaa');
  assert.equal(match.offset, 40);
});

test('packAddress packs 0x00401196 as 64-bit little-endian bytes and python literal', () => {
  const packed = packAddress('0x00401196', 64, 'little');
  assert.ok(packed);
  assert.equal(packed.hexBytes, '96 11 40 00 00 00 00 00');
  assert.equal(packed.pythonLiteral, 'b"\\x96\\x11\\x40\\x00\\x00\\x00\\x00\\x00"');
});

test('evaluateStackFrame detects canary abort vs RIP overwrite accurately', () => {
  const safe = evaluateStackFrame(48, true, 64);
  assert.equal(safe.verdict, 'Safe');

  const trapped = evaluateStackFrame(76, true, 64);
  assert.equal(trapped.canaryCorrupted, true);
  assert.equal(trapped.verdict, 'Canary Trap (SIGABRT)');

  const rip = evaluateStackFrame(80, false, 64);
  assert.equal(rip.returnAddressOverwritten, true);
  assert.equal(rip.verdict, 'RIP Control Achieved');

  assert.equal(rot13('atlas'), 'ngynf');
});
