import type { Challenge } from '../types';

/**
 * Built-in Nightmare curriculum seed modules (educational binary analysis & defensive study).
 * Plaintext sample flags are hashed via SHA-256 in Firestore; learners can verify
 * flags extracted from the Nightmare.zip Archive Explorer or solved during lab study.
 */
export const NIGHTMARE_SEED_CHALLENGES: Challenge[] = [
  {
    id: 'nm-00-assembly-registers',
    moduleNum: '00',
    moduleName: 'Intro to Assembly & Tooling',
    title: 'x86-64 Calling Convention Audit',
    category: 'Reversing',
    difficulty: 'Beginner',
    arch: 'x86-64',
    points: 50,
    summary:
      'Analyze System V AMD64 calling conventions, stack pointer alignment, and ELF section headers inside the Nightmare starter archive.',
    objective:
      'Review registers_guide.md in Nightmare/00-intro_assembly/ and identify the six integer argument registers and stack alignment requirement.',
    zipPath: 'Nightmare/00-intro_assembly/registers_guide.md',
    flagHash: '371d95813992ec66ff2661e7a8a475185242e8fdebdf54975a56faf77f3824d2',
    flagHint: 'atlas{nm00_...} (Check sample flag button or inspect registers_guide)',
    sampleFlag: 'atlas{nm00_sysv_amd64_regs}',
    published: true,
    mitigations: {
      nx: 'Enabled',
      pie: 'Enabled',
      canary: 'Enabled',
      relro: 'Full RELRO',
    },
    exploitTemplate: `#!/usr/bin/env python3
"""Module 00: System V AMD64 Register Reference Helper"""
ARG_REGS = ["RDI", "RSI", "RDX", "RCX", "R8", "R9"]
STACK_ALIGNMENT = 16

for idx, reg in enumerate(ARG_REGS, start=1):
    print(f"Arg {idx}: {reg}")
print(f"Required stack alignment before CALL: {STACK_ALIGNMENT} bytes")
`,
    authorUid: 'system-seed',
    stackPreset: {
      bufSize: 16,
      savedRbpOffset: 16,
      retOffset: 24,
      targetAddr: '0x00401140',
      targetSymbol: 'check_alignment',
    },
  },
  {
    id: 'nm-03-beginner-re-strings',
    moduleNum: '03',
    moduleName: 'Beginner Reverse Engineering',
    title: 'Static RODATA & ELF Inspection',
    category: 'Reversing',
    difficulty: 'Beginner',
    arch: 'x86-64',
    points: 100,
    summary:
      'Perform static analysis on a 64-bit PIE ELF binary from Nightmare.zip without executing it. Parse the ELF header and extract embedded ASCII strings.',
    objective:
      'Open Nightmare/03-beginner_re/csaw18_strings/strings_lab.bin in the Archive Explorer, verify PIE/NX headers, and extract the flag from .rodata strings.',
    zipPath: 'Nightmare/03-beginner_re/csaw18_strings/strings_lab.bin',
    flagHash: 'dce8c166c9e94b1311bacac443daee4675d19bf550bcf4e41a8601fb386921d0',
    flagHint: 'Extractable directly from strings_lab.bin in Archive Explorer',
    sampleFlag: 'atlas{nm03_static_rodata_inspection}',
    published: true,
    mitigations: {
      nx: 'Enabled',
      pie: 'Enabled',
      canary: 'Disabled',
      relro: 'Partial / Full',
    },
    exploitTemplate: `#!/usr/bin/env python3
"""Module 03: Static ELF String Extractor"""
import re, pathlib

data = pathlib.Path("strings_lab.bin").read_bytes()
for match in re.finditer(rb"[ -~]{6,}", data):
    text = match.group().decode("ascii")
    if "atlas{" in text:
        print(f"Offset 0x{match.start():x}: {text}")
`,
    authorUid: 'system-seed',
    stackPreset: {
      bufSize: 24,
      savedRbpOffset: 24,
      retOffset: 32,
      targetAddr: '0x00001060',
      targetSymbol: 'verify_key',
    },
  },
  {
    id: 'nm-04-bof-variable',
    moduleNum: '04',
    moduleName: 'Stack Variable Boundaries',
    title: 'Local Frame Guard Analysis (BOI Lab)',
    category: 'Stack',
    difficulty: 'Beginner',
    arch: 'x86-64',
    points: 150,
    summary:
      'Study how adjacent local variables sit in contiguous stack slots and why unbounded input functions violate memory safety boundaries.',
    objective:
      'Inspect boi_lab.c and boi_lab.bin in Archive Explorer. Use the interactive Stack Frame Visualizer below to observe the 20-byte offset between input_buf and guard_tag.',
    zipPath: 'Nightmare/04-bof_variable/boi_lab/boi_lab.c',
    flagHash: 'dfabd4b9303afec96710c9922bce02339d8094df34a101bbca473c919bb1fc67',
    flagHint: 'Inspect boi_lab.bin strings in Archive Explorer',
    sampleFlag: 'atlas{nm04_stack_variable_layout}',
    published: true,
    mitigations: {
      nx: 'Enabled',
      pie: 'No PIE',
      canary: 'Disabled',
      relro: 'No RELRO',
    },
    exploitTemplate: `#!/usr/bin/env python3
"""Module 04: Local Stack Variable Boundary Audit"""
import struct

BUF_SIZE = 20
TARGET_GUARD = 0xcaf3baee

# Remediation: replace unsafe reads with fgets(input_buf, sizeof(input_buf), stdin)
print(f"Buffer length before adjacent local variable: {BUF_SIZE} bytes")
print(f"Little-endian guard word: {struct.pack('<I', TARGET_GUARD).hex()}")
`,
    authorUid: 'system-seed',
    stackPreset: {
      bufSize: 20,
      savedRbpOffset: 24,
      retOffset: 32,
      targetAddr: '0xcaf3baee',
      targetSymbol: 'guard_tag',
    },
  },
  {
    id: 'nm-05-bof-callfunction',
    moduleNum: '05',
    moduleName: 'Control Flow & Return Addresses',
    title: 'Saved RIP Frame Layout (GetIt Lab)',
    category: 'Stack',
    difficulty: 'Intermediate',
    arch: 'x86-64',
    points: 200,
    summary:
      'Examine how function epilogues restore Saved RBP and Saved RIP from the stack and how stack canaries (-fstack-protector-strong) detect frame corruption.',
    objective:
      'Calculate the exact distance from a 32-byte stack buffer to Saved RIP (40 bytes) using the Cyclic Pattern tool and verify the mitigation flags on getit_lab.bin.',
    zipPath: 'Nightmare/05-bof_callfunction/getit_lab/getit_lab.bin',
    flagHash: 'bf0777bffba9b40d9ddf47913242fe21b4dcb5614a3ab930db6da3db759b0bf8',
    flagHint: 'Inspect getit_lab.bin strings in Archive Explorer',
    sampleFlag: 'atlas{nm05_control_flow_integrity}',
    published: true,
    mitigations: {
      nx: 'Enabled',
      pie: 'No PIE',
      canary: 'Disabled',
      relro: 'Partial / Full',
    },
    exploitTemplate: `#!/usr/bin/env python3
"""Module 05: Saved RIP Offset & Canary Mitigation Study"""
import struct

BUFFER_BYTES = 32
SAVED_RBP_BYTES = 8
SAVED_RIP_OFFSET = BUFFER_BYTES + SAVED_RBP_BYTES
AUDIT_FN_ADDR = 0x401196

print(f"Offset to Saved RIP: {SAVED_RIP_OFFSET} bytes")
print(f"Target symbol address (p64): {struct.pack('<Q', AUDIT_FN_ADDR).hex()}")
`,
    authorUid: 'system-seed',
    stackPreset: {
      bufSize: 32,
      savedRbpOffset: 32,
      retOffset: 40,
      targetAddr: '0x00401196',
      targetSymbol: 'print_audit_banner',
    },
  },
  {
    id: 'nm-07-rop-nx-defense',
    moduleNum: '07',
    moduleName: 'NX Mitigation & Code Reuse',
    title: 'Non-Executable Stack & Gadget Defense',
    category: 'ROP',
    difficulty: 'Intermediate',
    arch: 'x86-64',
    points: 300,
    summary:
      'Explore PT_GNU_STACK permission flags that enforce Non-Executable (NX / W^X) memory pages, alongside ASLR and hardware Control-Flow Integrity.',
    objective:
      'Verify PT_GNU_STACK NX enforcement on rop_lab.bin in the Archive Explorer and review nx_mitigation_notes.md.',
    zipPath: 'Nightmare/07-rop_concepts/rop_lab.bin',
    flagHash: '64ffe58852a50054b4e40961f364cc7592c90553368656b22535e57f00741246',
    flagHint: 'Inspect rop_lab.bin in Archive Explorer',
    sampleFlag: 'atlas{nm07_nx_defense_lab}',
    published: true,
    mitigations: {
      nx: 'Enabled',
      pie: 'No PIE',
      canary: 'Disabled',
      relro: 'Partial / Full',
    },
    exploitTemplate: `#!/usr/bin/env python3
"""Module 07: NX & Alignment Verification Script"""
# Hardware defense note: Intel CET Shadow Stack verifies RET targets against an isolated shadow stack.
STACK_ALIGN_REQUIREMENT = 16
print(f"Verify 16-byte RSP alignment for MOVAPS instructions: mod {STACK_ALIGN_REQUIREMENT} == 0")
`,
    authorUid: 'system-seed',
    stackPreset: {
      bufSize: 48,
      savedRbpOffset: 48,
      retOffset: 56,
      targetAddr: '0x00401204',
      targetSymbol: 'pop_rdi_ret',
    },
  },
  {
    id: 'nm-08-format-strings',
    moduleNum: '08',
    moduleName: 'Format String Auditing',
    title: 'Variadic Printf Argument Discipline',
    category: 'Format',
    difficulty: 'Intermediate',
    arch: 'x86-64',
    points: 250,
    summary:
      'Analyze how uncontrolled format specifiers (%p, %s, %n) read or mutate stack arguments in C programs and how -Wformat-security prevents bugs at compile time.',
    objective:
      'Review fmt_audit.c in Nightmare/08-format_strings/ and use the Format Specifier Inspector in the Tooling Lab to calculate stack argument indexing.',
    zipPath: 'Nightmare/08-format_strings/fmt_audit.c',
    flagHash: '9e649569e9c06395afdccd48a6a8d4daca4c5972aa0a07b835581dcb56f48b78',
    flagHint: 'atlas{nm08_...} (Format security lab)',
    sampleFlag: 'atlas{nm08_wformat_security_guard}',
    published: true,
    mitigations: {
      nx: 'Enabled',
      pie: 'Enabled',
      canary: 'Enabled',
      relro: 'Full RELRO',
    },
    exploitTemplate: `#!/usr/bin/env python3
"""Module 08: Format Specifier Static Audit"""
# Always supply a constant format string literal:
#   Safe:   printf("%s\\n", user_input);
#   Unsafe: printf(user_input);
# Enable compiler check: -Werror=format-security -D_FORTIFY_SOURCE=2
print("Static audit verified: constant format literal required.")
`,
    authorUid: 'system-seed',
    stackPreset: {
      bufSize: 40,
      savedRbpOffset: 40,
      retOffset: 48,
      targetAddr: '0x00404020',
      targetSymbol: 'got_printf',
    },
  },
  {
    id: 'nm-10-heap-allocator',
    moduleNum: '10',
    moduleName: 'Heap Allocator Internals',
    title: 'Glibc Chunk Metadata & Safe-Linking',
    category: 'Heap',
    difficulty: 'Advanced',
    arch: 'x86-64',
    points: 400,
    summary:
      'Inspect dynamic heap chunk metadata (prev_size, size, PREV_INUSE bit), tcache bins, and modern glibc Safe-Linking pointer obfuscation.',
    objective:
      'Study allocator_notes.md in Nightmare/10-heap_basics/ and calculate aligned chunk sizes plus Safe-Linking pointer masks.',
    zipPath: 'Nightmare/10-heap_basics/allocator_notes.md',
    flagHash: '34f87b276b74d2328223d4fefffad89fb8a64b6e7666f11f001c75a5b902d95c',
    flagHint: 'atlas{nm10_...} (Heap allocator metadata lab)',
    sampleFlag: 'atlas{nm10_glibc_safe_linking}',
    published: true,
    mitigations: {
      nx: 'Enabled',
      pie: 'Enabled',
      canary: 'Enabled',
      relro: 'Full RELRO',
    },
    exploitTemplate: `#!/usr/bin/env python3
"""Module 10: Glibc Chunk Size & Safe-Linking Calculator"""
def chunk_size(requested: int) -> int:
    # 64-bit minimum chunk is 0x20, 16-byte aligned with 8-byte header overhead
    return max(0x20, ((requested + 8 + 15) // 16) * 16)

def safe_link(chunk_addr: int, next_ptr: int) -> int:
    return next_ptr ^ (chunk_addr >> 12)

print(f"malloc(24) -> aligned chunk size: {hex(chunk_size(24))}")
print(f"Safe-Linked fd example: {hex(safe_link(0x5555555592a0, 0x5555555592c0))}")
`,
    authorUid: 'system-seed',
    stackPreset: {
      bufSize: 32,
      savedRbpOffset: 32,
      retOffset: 40,
      targetAddr: '0x5555555592a0',
      targetSymbol: 'tcache_entry',
    },
  },
];
