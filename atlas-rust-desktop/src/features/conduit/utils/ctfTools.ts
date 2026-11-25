// Pure CTF binary exploitation & educational utilities integrated from Atlas CTF (noprivacynofreedom/nightmare)

const LOWER = 'abcdefghijklmnopqrstuvwxyz';

export function generateCyclicPattern(length: number): string {
  const safeLen = Math.max(4, Math.min(4096, Math.floor(length)));
  let out = '';
  for (let a = 0; a < LOWER.length && out.length < safeLen; a++) {
    for (let b = 0; b < LOWER.length && out.length < safeLen; b++) {
      for (let c = 0; c < LOWER.length && out.length < safeLen; c++) {
        for (let d = 0; d < LOWER.length && out.length < safeLen; d++) {
          out += LOWER[d] + LOWER[c] + LOWER[b] + LOWER[a];
          if (out.length >= safeLen) break;
        }
      }
    }
  }
  return out.slice(0, safeLen);
}

export function findCyclicOffset(
  pattern: string,
  query: string,
  endianness: 'little' | 'big' = 'little'
): { offset: number; decodedAscii: string } | null {
  const trimmed = query.trim();
  if (!trimmed) return null;

  let needle = trimmed;
  if (/^0x[0-9a-fA-F]+$/.test(trimmed)) {
    let hex = trimmed.slice(2);
    if (hex.length % 2 !== 0) hex = '0' + hex;
    const bytes: number[] = [];
    for (let i = 0; i < hex.length; i += 2) {
      bytes.push(parseInt(hex.slice(i, i + 2), 16));
    }
    if (endianness === 'little') {
      bytes.reverse();
    }
    needle = bytes.map((b) => String.fromCharCode(b)).join('');
  }

  if (!needle) return null;
  const idx = pattern.indexOf(needle);
  if (idx === -1) return null;
  return { offset: idx, decodedAscii: needle };
}

export function packAddress(
  hexInput: string,
  bits: 32 | 64 = 64,
  endianness: 'little' | 'big' = 'little'
): { hexBytes: string; pythonLiteral: string; normalizedHex: string } | null {
  const clean = hexInput.trim().replace(/^0x/i, '');
  if (!clean || !/^[0-9a-fA-F]+$/.test(clean)) return null;

  const byteCount = bits / 8;
  let value: bigint;
  try {
    value = BigInt('0x' + clean);
  } catch {
    return null;
  }

  const maxVal = (1n << BigInt(bits)) - 1n;
  if (value < 0n || value > maxVal) return null;

  const bytes: number[] = [];
  for (let i = 0; i < byteCount; i++) {
    const shift = BigInt(i * 8);
    bytes.push(Number((value >> shift) & 0xffn));
  }
  if (endianness === 'big') {
    bytes.reverse();
  }

  const hexBytes = bytes.map((b) => b.toString(16).padStart(2, '0')).join(' ');
  const pythonLiteral = `b"${bytes.map((b) => `\\x${b.toString(16).padStart(2, '0')}`).join('')}"`;
  const normalizedHex = `0x${value.toString(16).padStart(byteCount * 2, '0')}`;

  return { hexBytes, pythonLiteral, normalizedHex };
}

export function rot13(input: string): string {
  return input.replace(/[a-zA-Z]/g, (ch) => {
    const base = ch <= 'Z' ? 65 : 97;
    return String.fromCharCode(((ch.charCodeAt(0) - base + 13) % 26) + base);
  });
}

export interface StackFrameState {
  bufferSize: number;
  inputLength: number;
  canaryEnabled: boolean;
  canaryCorrupted: boolean;
  savedRbpCorrupted: boolean;
  returnAddressOverwritten: boolean;
  verdict: 'Safe' | 'Canary Trap (SIGABRT)' | 'Saved RBP Overwritten' | 'RIP Control Achieved';
}

export function evaluateStackFrame(
  inputLength: number,
  canaryEnabled: boolean,
  bufferSize = 64
): StackFrameState {
  const canaryOffset = bufferSize;
  const rbpOffset = canaryEnabled ? bufferSize + 8 : bufferSize;
  const ripOffset = rbpOffset + 8;

  const canaryCorrupted = canaryEnabled && inputLength > canaryOffset;
  const savedRbpCorrupted = inputLength > rbpOffset;
  const returnAddressOverwritten = inputLength > ripOffset;

  let verdict: StackFrameState['verdict'] = 'Safe';
  if (canaryCorrupted) {
    verdict = 'Canary Trap (SIGABRT)';
  } else if (returnAddressOverwritten) {
    verdict = 'RIP Control Achieved';
  } else if (savedRbpCorrupted) {
    verdict = 'Saved RBP Overwritten';
  }

  return {
    bufferSize,
    inputLength,
    canaryEnabled,
    canaryCorrupted,
    savedRbpCorrupted,
    returnAddressOverwritten,
    verdict,
  };
}
