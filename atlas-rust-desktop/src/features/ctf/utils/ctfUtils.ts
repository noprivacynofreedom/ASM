import JSZip from 'jszip';
import type { ParsedElfInfo, ZipEntryItem } from '../types';

/**
 * Compute lowercase SHA-256 hex digest using Web Crypto API.
 */
export async function sha256Hex(input: string): Promise<string> {
  const encoded = new TextEncoder().encode(input.trim());
  const hashBuffer = await crypto.subtle.digest('SHA-256', encoded);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Check if raw bytes begin with the ELF magic signature (0x7F 'E' 'L' 'F').
 */
export function isElfBytes(bytes?: Uint8Array): boolean {
  if (!bytes || bytes.length < 4) return false;
  return bytes[0] === 0x7f && bytes[1] === 0x45 && bytes[2] === 0x4c && bytes[3] === 0x46;
}

/**
 * Parse ELF header and program header security attributes client-side.
 */
export function parseElfHeader(bytes: Uint8Array): ParsedElfInfo | null {
  if (!isElfBytes(bytes) || bytes.length < 52) return null;

  const is64 = bytes[4] === 2;
  const littleEndian = bytes[5] === 1;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

  const u16 = (offset: number) =>
    offset + 2 <= bytes.length ? view.getUint16(offset, littleEndian) : 0;
  const u32 = (offset: number) =>
    offset + 4 <= bytes.length ? view.getUint32(offset, littleEndian) : 0;
  const u64Hex = (offset: number) => {
    if (offset + 8 > bytes.length) return '0x0';
    const lo = view.getUint32(offset, littleEndian);
    const hi = view.getUint32(offset + 4, littleEndian);
    const val = littleEndian ? (BigInt(hi) << 32n) | BigInt(lo) : (BigInt(lo) << 32n) | BigInt(hi);
    return `0x${val.toString(16)}`;
  };

  const eType = u16(16);
  const eMachine = u16(18);
  const entryPoint = is64 ? u64Hex(24) : `0x${u32(24).toString(16)}`;
  const phOff = is64 ? Number(view.getBigUint64(32, littleEndian)) : u32(28);
  const phEntSize = is64 ? u16(54) : u16(42);
  const phNum = is64 ? u16(56) : u16(44);
  const shNum = is64 ? u16(60) : u16(48);

  const typeMap: Record<number, string> = {
    1: 'ET_REL (Relocatable)',
    2: 'ET_EXEC (Executable)',
    3: 'ET_DYN (Shared / PIE)',
    4: 'ET_CORE (Core)',
  };

  const machineMap: Record<number, string> = {
    3: 'x86 (EM_386)',
    40: 'ARM (EM_ARM)',
    62: 'x86-64 (EM_X86_64)',
    183: 'AArch64 (EM_AARCH64)',
    243: 'RISC-V (EM_RISCV)',
  };

  let nx: ParsedElfInfo['nx'] = 'Unknown';
  let relro: ParsedElfInfo['relro'] = 'No RELRO';
  const pie: ParsedElfInfo['pie'] =
    eType === 3 ? 'Enabled' : eType === 2 ? 'No PIE' : 'Unknown';

  // Inspect program headers if present in buffer
  if (phOff > 0 && phEntSize >= 32 && phNum > 0 && phNum <= 64) {
    for (let i = 0; i < phNum; i++) {
      const base = phOff + i * phEntSize;
      if (base + phEntSize > bytes.length) break;
      const pType = u32(base);
      const pFlags = is64 ? u32(base + 4) : u32(base + 24);
      // PT_GNU_STACK = 0x6474e551
      if (pType === 0x6474e551) {
        nx = (pFlags & 0x1) === 0 ? 'Enabled' : 'Disabled';
      }
      // PT_GNU_RELRO = 0x6474e552
      if (pType === 0x6474e552) {
        relro = 'Partial / Full';
      }
    }
  }

  return {
    valid: true,
    bitness: is64 ? '64-bit' : '32-bit',
    endianness: littleEndian ? 'Little Endian' : 'Big Endian',
    type: typeMap[eType] || `Type ${eType}`,
    machine: machineMap[eMachine] || `Machine ${eMachine}`,
    entryPoint,
    programHeaderCount: phNum,
    sectionHeaderCount: shNum,
    nx,
    pie,
    relro,
  };
}

/**
 * Extract printable ASCII strings from raw bytes (equivalent to `strings -n minLen`).
 */
export function extractAsciiStrings(bytes: Uint8Array, minLength = 4, limit = 300): Array<{ offset: string; value: string }> {
  const results: Array<{ offset: string; value: string }> = [];
  let current = '';
  let startOffset = 0;

  for (let i = 0; i < bytes.length; i++) {
    const b = bytes[i];
    if (b >= 0x20 && b <= 0x7e) {
      if (current.length === 0) startOffset = i;
      current += String.fromCharCode(b);
    } else {
      if (current.length >= minLength) {
        results.push({
          offset: `0x${startOffset.toString(16).padStart(6, '0')}`,
          value: current,
        });
        if (results.length >= limit) break;
      }
      current = '';
    }
  }
  if (current.length >= minLength && results.length < limit) {
    results.push({
      offset: `0x${startOffset.toString(16).padStart(6, '0')}`,
      value: current,
    });
  }
  return results;
}

/**
 * Format a slice of bytes into a classic 16-byte-per-row hex + ASCII dump.
 */
export function formatHexDump(bytes: Uint8Array, startOffset = 0, maxBytes = 512): Array<{
  offset: string;
  hexLeft: string;
  hexRight: string;
  ascii: string;
}> {
  const rows: Array<{ offset: string; hexLeft: string; hexRight: string; ascii: string }> = [];
  const end = Math.min(bytes.length, startOffset + maxBytes);

  for (let i = startOffset; i < end; i += 16) {
    const slice = bytes.slice(i, Math.min(i + 16, end));
    const hexParts = Array.from(slice).map((b) => b.toString(16).padStart(2, '0'));
    while (hexParts.length < 16) hexParts.push('  ');
    const ascii = Array.from(slice)
      .map((b) => (b >= 0x20 && b <= 0x7e ? String.fromCharCode(b) : '.'))
      .join('');

    rows.push({
      offset: i.toString(16).padStart(8, '0'),
      hexLeft: hexParts.slice(0, 8).join(' '),
      hexRight: hexParts.slice(8, 16).join(' '),
      ascii,
    });
  }
  return rows;
}

/**
 * Generate a De Bruijn cyclic sequence (order n=4) compatible with pwntools cyclic().
 */
export function generateCyclicPattern(length: number): string {
  const safeLen = Math.max(4, Math.min(length, 4096));
  const alphabet = 'abcdefghijklmnopqrstuvwxyz';
  const k = alphabet.length;
  const n = 4;
  const a = new Array<number>(k * n).fill(0);
  const sequence: number[] = [];

  function db(t: number, p: number) {
    if (sequence.length >= safeLen + n) return;
    if (t > n) {
      if (n % p === 0) {
        for (let i = 1; i <= p; i++) {
          sequence.push(a[i]);
          if (sequence.length >= safeLen + n) return;
        }
      }
    } else {
      a[t] = a[t - p];
      db(t + 1, p);
      for (let j = a[t - p] + 1; j < k; j++) {
        if (sequence.length >= safeLen + n) return;
        a[t] = j;
        db(t + 1, t);
      }
    }
  }

  db(1, 1);
  return sequence
    .slice(0, safeLen)
    .map((idx) => alphabet[idx])
    .join('');
}

/**
 * Locate the byte offset of a 4-byte ASCII or hex query inside a cyclic pattern.
 */
export function findCyclicOffset(query: string, endian: 'little' | 'big' = 'little'): {
  found: boolean;
  offset: number;
  decodedAscii: string;
} {
  const trimmed = query.trim();
  if (!trimmed) return { found: false, offset: -1, decodedAscii: '' };

  let needle = trimmed;
  if (/^0x[0-9a-fA-F]+$/.test(trimmed)) {
    let hex = trimmed.slice(2);
    if (hex.length % 2 === 1) hex = '0' + hex;
    const bytes: number[] = [];
    for (let i = 0; i < hex.length; i += 2) {
      bytes.push(parseInt(hex.slice(i, i + 2), 16));
    }
    if (endian === 'little') bytes.reverse();
    needle = bytes.map((b) => String.fromCharCode(b)).join('').slice(0, 4);
  }

  if (needle.length < 4) {
    return { found: false, offset: -1, decodedAscii: needle };
  }

  const pattern = generateCyclicPattern(4096);
  const idx = pattern.indexOf(needle.slice(0, 4));
  return { found: idx !== -1, offset: idx, decodedAscii: needle };
}

/**
 * Pack a 32-bit or 64-bit integer string into escaped hex bytes (p32 / p64).
 */
export function packIntegerBytes(
  valueStr: string,
  bits: 32 | 64,
  endian: 'little' | 'big'
): { hexSpaced: string; pythonLiteral: string; decimal: string } | null {
  try {
    const clean = valueStr.trim();
    if (!clean) return null;
    const val = clean.startsWith('0x') || clean.startsWith('0X') ? BigInt(clean) : BigInt(clean);
    const byteCount = bits / 8;
    const mask = (1n << BigInt(bits)) - 1n;
    const normalized = val & mask;
    const bytes: number[] = [];
    for (let i = 0; i < byteCount; i++) {
      bytes.push(Number((normalized >> BigInt(i * 8)) & 0xffn));
    }
    if (endian === 'big') bytes.reverse();
    return {
      hexSpaced: bytes.map((b) => b.toString(16).padStart(2, '0')).join(' '),
      pythonLiteral: `b"${bytes.map((b) => `\\x${b.toString(16).padStart(2, '0')}`).join('')}"`,
      decimal: normalized.toString(10),
    };
  } catch {
    return null;
  }
}

/**
 * Construct a minimal valid 64-bit ELF binary header + readable strings for educational inspection.
 */
function buildSampleElfBinary(options: {
  pie: boolean;
  nx: boolean;
  relro: boolean;
  entryAddr: number;
  embeddedStrings: string[];
}): Uint8Array {
  const stringPayload = new TextEncoder().encode(options.embeddedStrings.join('\0') + '\0');
  const phOff = 64;
  const phEntSize = 56;
  const phNum = options.relro ? 2 : 1;
  const dataOffset = phOff + phEntSize * phNum + 16;
  const totalLen = Math.max(256, dataOffset + stringPayload.length + 16);
  const buf = new Uint8Array(totalLen);
  const view = new DataView(buf.buffer);

  // ELF Magic
  buf[0] = 0x7f;
  buf[1] = 0x45;
  buf[2] = 0x4c;
  buf[3] = 0x46;
  buf[4] = 2; // 64-bit
  buf[5] = 1; // Little endian
  buf[6] = 1; // ELF version

  view.setUint16(16, options.pie ? 3 : 2, true); // ET_DYN vs ET_EXEC
  view.setUint16(18, 62, true); // EM_X86_64
  view.setUint32(20, 1, true);
  view.setBigUint64(24, BigInt(options.entryAddr), true); // e_entry
  view.setBigUint64(32, BigInt(phOff), true); // e_phoff
  view.setUint16(52, 64, true); // e_ehsize
  view.setUint16(54, phEntSize, true);
  view.setUint16(56, phNum, true);
  view.setUint16(60, 14, true); // e_shnum

  // Program Header 0: PT_GNU_STACK
  view.setUint32(phOff, 0x6474e551, true);
  view.setUint32(phOff + 4, options.nx ? 0x6 : 0x7, true); // RW vs RWX

  // Program Header 1: PT_GNU_RELRO
  if (options.relro) {
    view.setUint32(phOff + phEntSize, 0x6474e552, true);
    view.setUint32(phOff + phEntSize + 4, 0x4, true);
  }

  buf.set(stringPayload, dataOffset);
  return buf;
}

/**
 * Generate an authentic educational Nightmare.zip archive in memory so learners can
 * immediately inspect directory structures, source files, analysis notes, and ELF headers,
 * or export it to disk.
 */
export async function buildStarterNightmareZip(): Promise<{
  blob: Blob;
  entries: ZipEntryItem[];
}> {
  const zip = new JSZip();

  zip.file(
    'Nightmare/README.md',
    `# Nightmare Curriculum Archive (Atlas CTF Edition)\n\nStructured study workspace for binary analysis, ELF security mitigations, stack frame layout, and memory safety education.\n\n## Directory Layout\n- 00-intro_assembly/: x86-64 register & calling convention reference\n- 03-beginner_re/: Static disassembly & symbol inspection lab\n- 04-bof_variable/: Stack frame variable boundary analysis\n- 05-bof_callfunction/: Control-flow integrity & return address mechanics\n- 07-rop_concepts/: NX mitigation & code-reuse defense lab\n- 08-format_strings/: Variadic printf specification study\n- 10-heap_basics/: Dynamic allocator chunk structure overview\n`
  );

  zip.file(
    'Nightmare/00-intro_assembly/registers_guide.md',
    `# x86-64 System V AMD64 Calling Convention\n\n- Argument Registers: RDI, RSI, RDX, RCX, R8, R9\n- Return Value Register: RAX\n- Stack Pointer: RSP (grows toward lower memory addresses)\n- Base Frame Pointer: RBP\n- Instruction Pointer: RIP\n\n## Defense Check\nCompile with: gcc -fstack-protector-strong -fPIE -pie -Wl,-z,relro,-z,now lab.c -o lab\n`
  );

  zip.file(
    'Nightmare/03-beginner_re/csaw18_strings/readme.md',
    `# Module 03: Beginner Reverse Engineering\n\nInspect the compiled ELF binary using the Strings Extractor and ELF Header Parser.\nObserve embedded read-only data (.rodata) symbols and check binary protection flags.\n`
  );
  zip.file(
    'Nightmare/03-beginner_re/csaw18_strings/strings_lab.bin',
    buildSampleElfBinary({
      pie: true,
      nx: true,
      relro: true,
      entryAddr: 0x1060,
      embeddedStrings: [
        'ELF64-x86-64',
        'GLIBC_2.34',
        'Atlas CTF Module 03 Static Inspection Lab',
        'atlas{nm03_static_rodata_inspection}',
        'main',
        'verify_key',
      ],
    })
  );

  zip.file(
    'Nightmare/04-bof_variable/boi_lab/boi_lab.c',
    `#include <stdio.h>\n#include <stdint.h>\n\n/* Educational memory boundary demonstration */\nint main(void) {\n    uint32_t guard_tag = 0xdeadbeef;\n    char input_buf[20];\n\n    puts("Atlas CTF Stack Boundary Lab");\n    /* Safe implementation uses fgets(input_buf, sizeof(input_buf), stdin); */\n    if (guard_tag == 0xcaf3baee) {\n        puts("Boundary transition observed.");\n    }\n    return 0;\n}\n`
  );
  zip.file(
    'Nightmare/04-bof_variable/boi_lab/boi_lab.bin',
    buildSampleElfBinary({
      pie: false,
      nx: true,
      relro: false,
      entryAddr: 0x401050,
      embeddedStrings: [
        'Atlas CTF Stack Boundary Lab',
        'guard_tag_offset=0x14',
        'atlas{nm04_stack_variable_layout}',
      ],
    })
  );

  zip.file(
    'Nightmare/05-bof_callfunction/getit_lab/analysis.py',
    `#!/usr/bin/env python3\n\"\"\"Atlas CTF Module 05 - Stack Frame & Mitigation Verification Helper\"\"\"\nimport struct\n\nBUFFER_SIZE = 32\nSAVED_RBP_SIZE = 8\nRETURN_OFFSET = BUFFER_SIZE + SAVED_RBP_SIZE\nTARGET_SYMBOL_ADDR = 0x401196  # print_audit_banner()\n\ndef describe_layout():\n    print(f"Buffer bytes     : {BUFFER_SIZE}")\n    print(f"Saved RBP offset : {BUFFER_SIZE}")\n    print(f"Saved RIP offset : {RETURN_OFFSET}")\n    print(f"Packed target    : {struct.pack('<Q', TARGET_SYMBOL_ADDR).hex()}")\n\nif __name__ == "__main__":\n    describe_layout()\n`
  );
  zip.file(
    'Nightmare/05-bof_callfunction/getit_lab/getit_lab.bin',
    buildSampleElfBinary({
      pie: false,
      nx: true,
      relro: true,
      entryAddr: 0x401070,
      embeddedStrings: [
        'print_audit_banner',
        'saved_rip_offset=40',
        'atlas{nm05_control_flow_integrity}',
      ],
    })
  );

  zip.file(
    'Nightmare/07-rop_concepts/nx_mitigation_notes.md',
    `# Module 07: NX Mitigation & Return-Oriented Programming Theory\n\nWhen PT_GNU_STACK lacks the PF_X flag (NX enabled), memory pages on the stack are marked non-executable.\nModern defenses pair NX with ASLR, PIE, Stack Canaries, and Control-Flow Integrity (Intel CET / ARM PAC).\n`
  );
  zip.file(
    'Nightmare/07-rop_concepts/rop_lab.bin',
    buildSampleElfBinary({
      pie: false,
      nx: true,
      relro: true,
      entryAddr: 0x401090,
      embeddedStrings: ['PT_GNU_STACK_NX', 'gadget_alignment_study', 'atlas{nm07_nx_defense_lab}'],
    })
  );

  zip.file(
    'Nightmare/08-format_strings/fmt_audit.c',
    `#include <stdio.h>\n\n/* Never pass untrusted input as the first argument to printf(). */\nvoid log_message_safe(const char *msg) {\n    printf("%s\\n", msg);\n}\n`
  );

  zip.file(
    'Nightmare/10-heap_basics/allocator_notes.md',
    `# Module 10: Dynamic Heap Allocator Internals\n\nStudy glibc malloc chunk headers (prev_size, size + AMP flags) and tcache/fastbin freelist integrity checks.\nModern glibc versions add Safe-Linking pointer mangling (fd ^ (pos >> 12)) to protect freelist pointers.\n`
  );

  const blob = await zip.generateAsync({ type: 'blob' });
  const entries = await parseZipBlob(blob);
  return { blob, entries };
}

/**
 * Extract and index any uploaded .zip archive (such as Nightmare.zip) into inspectable entries.
 */
export async function parseZipBlob(file: Blob): Promise<ZipEntryItem[]> {
  const zip = await JSZip.loadAsync(file);
  const items: ZipEntryItem[] = [];

  const fileNames = Object.keys(zip.files).sort((a, b) => a.localeCompare(b));

  for (const fullPath of fileNames) {
    const entry = zip.files[fullPath];
    const cleanName = fullPath.replace(/\/$/, '').split('/').pop() || fullPath;

    if (entry.dir) {
      items.push({
        path: fullPath,
        name: cleanName,
        dir: true,
        size: 0,
      });
      continue;
    }

    const bytes = await entry.async('uint8array');
    const elf = isElfBytes(bytes);
    const lower = cleanName.toLowerCase();
    const isLikelyText =
      !elf &&
      (/\.(md|txt|c|h|cpp|py|sh|json|yml|yaml|makefile|s|asm|js|ts|cfg|ini|log)$/i.test(lower) ||
        lower === 'makefile' ||
        lower === 'readme' ||
        (bytes.length < 120000 && !bytes.slice(0, 512).includes(0)));

    items.push({
      path: fullPath,
      name: cleanName,
      dir: false,
      size: bytes.length,
      bytes,
      text: isLikelyText ? new TextDecoder().decode(bytes) : undefined,
      isElf: elf,
    });
  }

  return items;
}
