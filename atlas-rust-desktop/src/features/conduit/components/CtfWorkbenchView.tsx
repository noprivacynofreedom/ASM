import { useMemo, useState } from 'react';
import {
  CheckCircle2,
  Cpu,
  FileCode2,
  Flag,
  KeyRound,
  Layers,
  Send,
  ShieldAlert,
  ShieldCheck,
  Terminal,
} from 'lucide-react';
import {
  evaluateStackFrame,
  findCyclicOffset,
  generateCyclicPattern,
  packAddress,
} from '../utils/ctfTools';

interface CtfWorkbenchViewProps {
  onBroadcastToSwarm: (message: string, target?: string) => void;
}

const STARTER_FLAG = 'atlas{nm03_static_rodata_inspection}';

async function sha256Hex(input: string): Promise<string> {
  const bytes = new TextEncoder().encode(input);
  const hashBuffer = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(hashBuffer))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

const STARTER_STRINGS = [
  { offset: '0x00002004', value: '/lib64/ld-linux-x86-64.so.2' },
  { offset: '0x00002028', value: 'Atlas CTF · Nightmare Module 03 (strings_lab.bin)' },
  { offset: '0x00002060', value: 'atlas{nm03_static_rodata_inspection}' },
  { offset: '0x00002090', value: 'Enter verification token:' },
];

export function CtfWorkbenchView({ onBroadcastToSwarm }: CtfWorkbenchViewProps) {
  // Cyclic Pattern & Offset state
  const [patternLen, setPatternLen] = useState(128);
  const [offsetQuery, setOffsetQuery] = useState('0x6161616b');
  const [endianness, setEndianness] = useState<'little' | 'big'>('little');

  // Address Packer state
  const [packInput, setPackInput] = useState('0x00401196');
  const [packBits, setPackBits] = useState<32 | 64>(64);

  // Stack Frame Visualizer state
  const [inputLength, setInputLength] = useState(48);
  const [canaryEnabled, setCanaryEnabled] = useState(true);

  // SHA-256 Flag Verifier state
  const [flagCandidate, setFlagCandidate] = useState('');
  const [flagStatus, setFlagStatus] = useState<'idle' | 'verified' | 'mismatch'>('idle');
  const [flagDigest, setFlagDigest] = useState<string>('');
  const [solvedPoints, setSolvedPoints] = useState(0);

  const pattern = useMemo(() => generateCyclicPattern(patternLen), [patternLen]);
  const offsetMatch = useMemo(
    () => findCyclicOffset(pattern, offsetQuery, endianness),
    [pattern, offsetQuery, endianness]
  );
  const packed = useMemo(
    () => packAddress(packInput, packBits, 'little'),
    [packInput, packBits]
  );
  const stackState = useMemo(
    () => evaluateStackFrame(inputLength, canaryEnabled, 64),
    [inputLength, canaryEnabled]
  );

  const handleVerifyFlag = async () => {
    const trimmed = flagCandidate.trim();
    if (!trimmed) return;
    const [candidateHash, targetHash] = await Promise.all([
      sha256Hex(trimmed),
      sha256Hex(STARTER_FLAG),
    ]);
    setFlagDigest(candidateHash);
    if (candidateHash === targetHash) {
      setFlagStatus('verified');
      setSolvedPoints(100);
    } else {
      setFlagStatus('mismatch');
    }
  };

  return (
    <div className="mx-auto max-w-[1280px] space-y-6">
      {/* Header */}
      <div className="flex flex-col justify-between gap-4 border-b border-[#20242E] pb-5 lg:flex-row lg:items-end">
        <div className="max-w-2xl">
          <h1 className="text-[22px] font-semibold tracking-tight text-[#F9FAFB]">
            Atlas CTF Workbench (/ctf)
          </h1>
          <p className="mt-1 text-[13.5px] text-[#9CA3AF]">
            Integrated from{' '}
            <span className="font-mono text-[#D1D5DB]">noprivacynofreedom/nightmare (main)</span>
            {' '}— Nightmare.zip binary analysis, interactive stack frame simulator, cyclic offset finder, and p64 packer.
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2.5 lg:flex-nowrap">
          <button
            type="button"
            onClick={() =>
              onBroadcastToSwarm(
                '/swarm claim nm-03-strings-lab',
                'nm-03-strings-lab'
              )
            }
            className="inline-flex items-center gap-1.5 rounded-lg border border-[#2C3240] bg-[#171B24] px-3.5 py-2 text-[13px] font-medium text-[#E5E7EB] hover:bg-[#1E232F] whitespace-nowrap shrink-0"
          >
            <Send className="h-3.5 w-3.5 text-blue-400" aria-hidden="true" />
            <span>Claim in Swarm (/swarm)</span>
          </button>
        </div>
      </div>

      {/* Top Row: Starter Binary Checksec + Strings & SHA-256 Flag Verification */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <section className="rounded-xl border border-[#222630] bg-[#14171D] xl:col-span-7">
          <div className="flex items-center justify-between border-b border-[#20242E] px-5 py-4">
            <div>
              <h2 className="text-[15px] font-semibold text-[#F9FAFB]">
                Nightmare.zip Inspector · strings_lab.bin
              </h2>
              <p className="mt-0.5 text-[12.5px] text-[#8B92A5]">
                ELF 64-bit x86-64 · Entry <span className="font-mono">0x00401060</span> · NX Enabled · PIE Enabled · Full RELRO
              </p>
            </div>
            <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[#22C55E] whitespace-nowrap">
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
              Mounted
            </span>
          </div>

          <div className="p-5 space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-[12.5px]">
              <div className="rounded-lg border border-[#222630] bg-[#101319] p-3">
                <p className="text-[#6B7280]">Architecture</p>
                <p className="mt-1 font-mono font-medium text-[#E5E7EB]">x86-64 ELF</p>
              </div>
              <div className="rounded-lg border border-[#222630] bg-[#101319] p-3">
                <p className="text-[#6B7280]">NX Bit</p>
                <p className="mt-1 font-mono font-medium text-[#22C55E]">Enabled</p>
              </div>
              <div className="rounded-lg border border-[#222630] bg-[#101319] p-3">
                <p className="text-[#6B7280]">PIE</p>
                <p className="mt-1 font-mono font-medium text-[#22C55E]">Enabled</p>
              </div>
              <div className="rounded-lg border border-[#222630] bg-[#101319] p-3">
                <p className="text-[#6B7280]">RELRO</p>
                <p className="mt-1 font-mono font-medium text-[#22C55E]">Full</p>
              </div>
            </div>

            <div>
              <p className="mb-2 flex items-center gap-1.5 text-[12.5px] font-medium text-[#9CA3AF]">
                <FileCode2 className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Extracted .rodata ASCII Strings</span>
              </p>
              <div className="divide-y divide-[#1D212B] rounded-lg border border-[#222630] bg-[#0D0F13]">
                {STARTER_STRINGS.map((row) => (
                  <div
                    key={row.offset}
                    className="flex items-center justify-between gap-3 px-3.5 py-2 font-mono text-[12px]"
                  >
                    <span className="shrink-0 tabular-nums text-[#6B7280]">{row.offset}</span>
                    <span className="min-w-0 flex-1 truncate text-[#D1D5DB]">{row.value}</span>
                    {row.value.startsWith('atlas{') && (
                      <button
                        type="button"
                        onClick={() => setFlagCandidate(row.value)}
                        className="shrink-0 text-[11.5px] font-sans font-medium text-blue-400 hover:text-blue-300"
                      >
                        Load into Verifier
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* SHA-256 Flag Verification */}
        <section className="rounded-xl border border-[#222630] bg-[#14171D] xl:col-span-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-[#20242E] px-5 py-4">
              <div className="flex items-center gap-2">
                <Flag className="h-4 w-4 text-blue-400" aria-hidden="true" />
                <h2 className="text-[15px] font-semibold text-[#F9FAFB]">
                  Module 03 · SHA-256 Flag Verification
                </h2>
              </div>
              <span className="font-mono text-[12px] tabular-nums text-[#9CA3AF]">
                +{solvedPoints} pts
              </span>
            </div>

            <div className="p-5 space-y-4">
              <p className="text-[13px] text-[#9CA3AF]">
                Verify flags client-side using Web Crypto SHA-256 digests (matching Firestore{' '}
                <span className="font-mono text-[#CBD5E1]">/challenges</span> schema where plaintext flags are never stored).
              </p>

              <div>
                <label htmlFor="ctf-flag-input" className="block text-[12.5px] font-medium text-[#D1D5DB]">
                  Flag Candidate
                </label>
                <div className="mt-1.5 flex gap-2">
                  <input
                    id="ctf-flag-input"
                    type="text"
                    value={flagCandidate}
                    onChange={(e) => setFlagCandidate(e.target.value)}
                    placeholder="atlas{...}"
                    className="min-w-0 flex-1 rounded-lg border border-[#272C38] bg-[#0D0F13] px-3 py-2 font-mono text-[12.5px] text-[#F3F4F6] placeholder-[#6B7280] focus:border-blue-500 focus:outline-none"
                  />
                  <button
                    type="button"
                    onClick={handleVerifyFlag}
                    className="rounded-lg bg-blue-600 px-3.5 py-2 text-[13px] font-medium text-white hover:bg-blue-500 whitespace-nowrap shrink-0"
                  >
                    Verify Flag
                  </button>
                </div>
              </div>

              {flagStatus === 'verified' && (
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3.5 text-[13px] text-emerald-300">
                  <div className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 font-medium">
                      <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                      Flag verified (+100 pts)
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        onBroadcastToSwarm(
                          `Verified Module 03 flag via SHA-256 digest (+100 pts) in Atlas CTF (/ctf).`
                        )
                      }
                      className="text-[12px] font-medium text-emerald-200 underline hover:text-white"
                    >
                      Announce in Swarm
                    </button>
                  </div>
                  <p className="mt-1.5 break-all font-mono text-[11px] text-emerald-200/80">
                    SHA-256: {flagDigest}
                  </p>
                </div>
              )}

              {flagStatus === 'mismatch' && (
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-[13px] text-red-300">
                  Digest mismatch — inspect <span className="font-mono">.rodata</span> strings and retry.
                </div>
              )}
            </div>
          </div>

          <div className="border-t border-[#20242E] px-5 py-3.5 text-[12px] text-[#8B92A5] flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              <KeyRound className="h-3.5 w-3.5 text-[#6B7280]" aria-hidden="true" />
              <span>RBAC Roles: Player · Organizer · Admin</span>
            </span>
            <span className="font-mono text-[#9CA3AF]">/ws/swarm ready</span>
          </div>
        </section>
      </div>

      {/* Bottom Row: CTF Tooling Lab (Cyclic Offset + Address Packer + Stack Frame Visualizer) */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        {/* Cyclic Pattern & Offset Calculator */}
        <section className="rounded-xl border border-[#222630] bg-[#14171D] p-5 space-y-4 xl:col-span-4">
          <div className="flex items-center gap-2">
            <Terminal className="h-4 w-4 text-blue-400" aria-hidden="true" />
            <h2 className="text-[14.5px] font-semibold text-[#F9FAFB]">
              Cyclic Pattern & Offset
            </h2>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="cyclic-len" className="block text-[12px] text-[#9CA3AF]">
                Length (bytes)
              </label>
              <input
                id="cyclic-len"
                type="number"
                min={16}
                max={1024}
                value={patternLen}
                onChange={(e) => setPatternLen(Number(e.target.value) || 128)}
                className="mt-1 w-full rounded-lg border border-[#272C38] bg-[#0D0F13] px-2.5 py-1.5 font-mono text-[12.5px] tabular-nums text-[#F3F4F6]"
              />
            </div>
            <div>
              <label htmlFor="cyclic-endian" className="block text-[12px] text-[#9CA3AF]">
                Endianness
              </label>
              <select
                id="cyclic-endian"
                value={endianness}
                onChange={(e) => setEndianness(e.target.value as 'little' | 'big')}
                className="mt-1 w-full rounded-lg border border-[#272C38] bg-[#0D0F13] px-2.5 py-1.5 text-[12.5px] text-[#F3F4F6]"
              >
                <option value="little">Little Endian</option>
                <option value="big">Big Endian</option>
              </select>
            </div>
          </div>

          <div>
            <label htmlFor="cyclic-query" className="block text-[12px] text-[#9CA3AF]">
              Lookup Value (Hex or ASCII)
            </label>
            <input
              id="cyclic-query"
              type="text"
              value={offsetQuery}
              onChange={(e) => setOffsetQuery(e.target.value)}
              className="mt-1 w-full rounded-lg border border-[#272C38] bg-[#0D0F13] px-3 py-1.5 font-mono text-[12.5px] text-[#F3F4F6]"
            />
          </div>

          <div className="rounded-lg border border-[#222630] bg-[#0D0F13] p-3">
            {offsetMatch ? (
              <div className="flex items-center justify-between text-[13px]">
                <span className="text-[#9CA3AF]">
                  Decoded <span className="font-mono text-[#E5E7EB]">"{offsetMatch.decodedAscii}"</span>
                </span>
                <span className="font-mono font-semibold tabular-nums text-[#22C55E]">
                  Offset: {offsetMatch.offset} bytes
                </span>
              </div>
            ) : (
              <p className="text-[12.5px] text-[#8B92A5]">No offset found in {patternLen}-byte sequence.</p>
            )}
          </div>
        </section>

        {/* p32 / p64 Endian Address Packer */}
        <section className="rounded-xl border border-[#222630] bg-[#14171D] p-5 space-y-4 xl:col-span-4">
          <div className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-blue-400" aria-hidden="true" />
            <h2 className="text-[14.5px] font-semibold text-[#F9FAFB]">
              p32 / p64 Address Packer
            </h2>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label htmlFor="pack-hex" className="block text-[12px] text-[#9CA3AF]">
                Target Address
              </label>
              <input
                id="pack-hex"
                type="text"
                value={packInput}
                onChange={(e) => setPackInput(e.target.value)}
                className="mt-1 w-full rounded-lg border border-[#272C38] bg-[#0D0F13] px-3 py-1.5 font-mono text-[12.5px] text-[#F3F4F6]"
              />
            </div>
            <div>
              <label htmlFor="pack-bits" className="block text-[12px] text-[#9CA3AF]">
                Width
              </label>
              <select
                id="pack-bits"
                value={packBits}
                onChange={(e) => setPackBits(Number(e.target.value) as 32 | 64)}
                className="mt-1 w-full rounded-lg border border-[#272C38] bg-[#0D0F13] px-2.5 py-1.5 font-mono text-[12.5px] text-[#F3F4F6]"
              >
                <option value={64}>64-bit</option>
                <option value={32}>32-bit</option>
              </select>
            </div>
          </div>

          {packed ? (
            <div className="space-y-2 rounded-lg border border-[#222630] bg-[#0D0F13] p-3 font-mono text-[12px]">
              <div>
                <p className="font-sans text-[11px] text-[#6B7280]">Little-Endian Hex Bytes</p>
                <p className="mt-0.5 text-[#E5E7EB] tabular-nums">{packed.hexBytes}</p>
              </div>
              <div className="border-t border-[#1D212B] pt-2">
                <p className="font-sans text-[11px] text-[#6B7280]">Python Byte Literal</p>
                <p className="mt-0.5 break-all text-blue-300">{packed.pythonLiteral}</p>
              </div>
            </div>
          ) : (
            <p className="text-[12.5px] text-red-400">Enter a valid hexadecimal address.</p>
          )}
        </section>

        {/* Interactive Stack Frame Visualizer */}
        <section className="rounded-xl border border-[#222630] bg-[#14171D] p-5 space-y-4 xl:col-span-4">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Layers className="h-4 w-4 text-blue-400" aria-hidden="true" />
              <h2 className="text-[14.5px] font-semibold text-[#F9FAFB]">
                Stack Frame Layout
              </h2>
            </div>
            <label className="inline-flex items-center gap-1.5 text-[12px] text-[#D1D5DB] cursor-pointer">
              <input
                type="checkbox"
                checked={canaryEnabled}
                onChange={(e) => setCanaryEnabled(e.target.checked)}
                className="h-3.5 w-3.5 rounded accent-blue-500"
              />
              <span>Stack Canary</span>
            </label>
          </div>

          <div>
            <div className="flex items-center justify-between text-[12px] text-[#9CA3AF]">
              <label htmlFor="stack-slider">Input Payload Length</label>
              <span className="font-mono tabular-nums text-[#E5E7EB]">{inputLength} bytes</span>
            </div>
            <input
              id="stack-slider"
              type="range"
              min={8}
              max={96}
              value={inputLength}
              onChange={(e) => setInputLength(Number(e.target.value))}
              className="mt-2 w-full accent-blue-500"
            />
          </div>

          <div className="space-y-1.5 font-mono text-[11.5px]">
            <div className="flex items-center justify-between rounded-md border border-[#242936] bg-[#10131A] px-3 py-1.5">
              <span className="text-[#CBD5E1]">char buf[64]</span>
              <span className="tabular-nums text-[#8B92A5]">{Math.min(64, inputLength)}/64 B</span>
            </div>
            {canaryEnabled && (
              <div
                className={`flex items-center justify-between rounded-md border px-3 py-1.5 ${
                  stackState.canaryCorrupted
                    ? 'border-red-500/40 bg-red-500/10 text-red-300'
                    : 'border-[#242936] bg-[#10131A] text-[#9CA3AF]'
                }`}
              >
                <span>Stack Canary (8 B)</span>
                <span>{stackState.canaryCorrupted ? 'CORRUPTED' : 'INTACT'}</span>
              </div>
            )}
            <div
              className={`flex items-center justify-between rounded-md border px-3 py-1.5 ${
                stackState.savedRbpCorrupted
                  ? 'border-amber-500/40 bg-amber-500/10 text-amber-300'
                  : 'border-[#242936] bg-[#10131A] text-[#9CA3AF]'
              }`}
            >
              <span>Saved RBP (8 B)</span>
              <span>{stackState.savedRbpCorrupted ? 'OVERWRITTEN' : 'INTACT'}</span>
            </div>
            <div
              className={`flex items-center justify-between rounded-md border px-3 py-1.5 ${
                stackState.returnAddressOverwritten
                  ? 'border-blue-500/40 bg-blue-500/10 text-blue-300'
                  : 'border-[#242936] bg-[#10131A] text-[#9CA3AF]'
              }`}
            >
              <span>Saved RIP (8 B)</span>
              <span>{stackState.returnAddressOverwritten ? 'CONTROLLED' : 'INTACT'}</span>
            </div>
          </div>

          <div className="flex items-center gap-2 text-[12.5px] font-medium">
            {stackState.verdict === 'Safe' ? (
              <ShieldCheck className="h-4 w-4 text-[#22C55E]" aria-hidden="true" />
            ) : (
              <ShieldAlert className="h-4 w-4 text-[#F59E0B]" aria-hidden="true" />
            )}
            <span className="text-[#E5E7EB]">Verdict: {stackState.verdict}</span>
          </div>
        </section>
      </div>
    </div>
  );
}
