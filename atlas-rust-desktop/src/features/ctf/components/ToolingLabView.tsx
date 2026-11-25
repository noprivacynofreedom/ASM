import React, { useMemo, useState } from 'react';
import { Check, Copy, Hash, Layers, Repeat, Wrench } from 'lucide-react';
import {
  findCyclicOffset,
  generateCyclicPattern,
  packIntegerBytes,
  sha256Hex,
} from '../utils/ctfUtils';

export function ToolingLabView() {
  // 1. Cyclic Pattern Tool
  const [patternLen, setPatternLen] = useState(128);
  const [crashQuery, setCrashQuery] = useState('0x6161616b');
  const [cyclicEndian, setCyclicEndian] = useState<'little' | 'big'>('little');

  // 2. Endian Packer
  const [packInput, setPackInput] = useState('0x00401196');
  const [packBits, setPackBits] = useState<32 | 64>(64);
  const [packEndian, setPackEndian] = useState<'little' | 'big'>('little');

  // 3. Encoding / Base Converter
  const [codecInput, setCodecInput] = useState('atlas{nightmare_lab}');

  // 4. SHA-256 Flag Hasher & Printf Stack Indexer
  const [flagPlain, setFlagPlain] = useState('atlas{custom_challenge_flag}');
  const [flagDigest, setFlagDigest] = useState('');
  const [fmtArgIndex, setFmtArgIndex] = useState(6);

  const [copiedId, setCopiedId] = useState<string | null>(null);

  const cyclicPattern = useMemo(() => generateCyclicPattern(patternLen), [patternLen]);
  const cyclicResult = useMemo(
    () => findCyclicOffset(crashQuery, cyclicEndian),
    [crashQuery, cyclicEndian]
  );

  const packedResult = useMemo(
    () => packIntegerBytes(packInput, packBits, packEndian),
    [packInput, packBits, packEndian]
  );

  const codecOutputs = useMemo(() => {
    const raw = codecInput;
    const bytes = new TextEncoder().encode(raw);
    const hex = Array.from(bytes)
      .map((b) => b.toString(16).padStart(2, '0'))
      .join(' ');
    let b64 = '';
    try {
      b64 = btoa(String.fromCharCode(...bytes));
    } catch {
      b64 = 'Unable to encode';
    }
    let decodedB64 = '';
    try {
      decodedB64 = atob(raw.trim());
    } catch {
      decodedB64 = 'Not valid Base64';
    }
    const urlEncoded = encodeURIComponent(raw);
    const rot13 = raw.replace(/[a-zA-Z]/g, (ch) => {
      const base = ch <= 'Z' ? 65 : 97;
      return String.fromCharCode(((ch.charCodeAt(0) - base + 13) % 26) + base);
    });
    return { hex, b64, decodedB64, urlEncoded, rot13, byteLen: bytes.length };
  }, [codecInput]);

  const copyText = async (id: string, val: string) => {
    await navigator.clipboard.writeText(val);
    setCopiedId(id);
    window.setTimeout(() => setCopiedId(null), 1500);
  };

  const computeFlagHash = async () => {
    const digest = await sha256Hex(flagPlain);
    setFlagDigest(digest);
  };

  const fmtStackLocation = useMemo(() => {
    const regArgs = ['RDI (fmt)', 'RSI (arg 1)', 'RDX (arg 2)', 'RCX (arg 3)', 'R8 (arg 4)', 'R9 (arg 5)'];
    if (fmtArgIndex < 6) {
      return `Register ${regArgs[fmtArgIndex]}`;
    }
    const offset = (fmtArgIndex - 6) * 8;
    return `Stack [RSP + 0x${offset.toString(16)}] (+${offset} bytes)`;
  }, [fmtArgIndex]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* 1. De Bruijn Cyclic Pattern & Offset Finder */}
      <section className="border border-slate-200 dark:border-slate-800 rounded-lg p-5 bg-white dark:bg-[#111827] space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Wrench className="w-4 h-4 text-amber-500" />
            <h2 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
              Cyclic Pattern & Offset Calculator
            </h2>
          </div>
          <span className="text-xs font-mono text-slate-500">De Bruijn n=4</span>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <label htmlFor="cyclic-len" className="text-slate-600 dark:text-slate-400">
              Pattern Length
            </label>
            <span className="font-mono tabular-nums text-slate-900 dark:text-slate-100">
              {patternLen} bytes
            </span>
          </div>
          <input
            id="cyclic-len"
            type="range"
            min={16}
            max={1024}
            step={8}
            value={patternLen}
            onChange={(e) => setPatternLen(Number(e.target.value))}
            className="w-full accent-amber-500 cursor-pointer"
          />
          <div className="relative">
            <pre className="p-3 rounded-md bg-slate-950 text-slate-200 font-mono text-xs break-all whitespace-pre-wrap max-h-28 overflow-y-auto pr-16">
              {cyclicPattern}
            </pre>
            <button
              type="button"
              onClick={() => void copyText('cyclic', cyclicPattern)}
              className="absolute right-2 top-2 inline-flex items-center gap-1 px-2 py-1 text-[11px] rounded bg-slate-800 text-slate-200 hover:bg-slate-700 cursor-pointer"
            >
              {copiedId === 'cyclic' ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
              {copiedId === 'cyclic' ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>

        <div className="pt-3 border-t border-slate-200 dark:border-slate-800 space-y-2.5">
          <p className="text-xs font-medium text-slate-700 dark:text-slate-300">
            Locate Offset from Register Value (Hex or 4-byte ASCII)
          </p>
          <div className="flex flex-wrap gap-2">
            <input
              type="text"
              value={crashQuery}
              onChange={(e) => setCrashQuery(e.target.value)}
              placeholder="e.g. 0x6161616b or kaaa"
              className="flex-1 min-w-[160px] px-3 py-1.5 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
            />
            <div className="flex items-center gap-1 p-0.5 rounded-md bg-slate-100 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800">
              {(['little', 'big'] as const).map((end) => (
                <button
                  key={end}
                  type="button"
                  onClick={() => setCyclicEndian(end)}
                  className={`px-2.5 py-1 text-xs font-medium rounded cursor-pointer whitespace-nowrap ${
                    cyclicEndian === end
                      ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                      : 'text-slate-500'
                  }`}
                >
                  {end === 'little' ? 'Little' : 'Big'}
                </button>
              ))}
            </div>
          </div>

          <div className="p-3 rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 text-xs font-mono flex items-center justify-between">
            <span className="text-slate-500">
              Needle: <span className="text-slate-900 dark:text-slate-200">{cyclicResult.decodedAscii || '—'}</span>
            </span>
            {cyclicResult.found ? (
              <span className="text-emerald-600 dark:text-emerald-400 font-semibold tabular-nums">
                Offset: {cyclicResult.offset} bytes (0x{cyclicResult.offset.toString(16)})
              </span>
            ) : (
              <span className="text-amber-600 dark:text-amber-400">Not found in 4096B pattern</span>
            )}
          </div>
        </div>
      </section>

      {/* 2. Endian Byte Packer (p32 / p64) */}
      <section className="border border-slate-200 dark:border-slate-800 rounded-lg p-5 bg-white dark:bg-[#111827] space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-amber-500" />
            <h2 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
              Address & Integer Packer (p32 / p64)
            </h2>
          </div>
          <span className="text-xs font-mono text-slate-500">struct.pack</span>
        </div>

        <div className="flex flex-wrap gap-2">
          <input
            type="text"
            value={packInput}
            onChange={(e) => setPackInput(e.target.value)}
            placeholder="0x00401196 or decimal"
            className="flex-1 min-w-[160px] px-3 py-1.5 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
          />
          <div className="flex items-center gap-1 p-0.5 rounded-md bg-slate-100 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800">
            {([32, 64] as const).map((b) => (
              <button
                key={b}
                type="button"
                onClick={() => setPackBits(b)}
                className={`px-2.5 py-1 text-xs font-mono rounded cursor-pointer ${
                  packBits === b
                    ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                    : 'text-slate-500'
                }`}
              >
                {b}-bit
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1 p-0.5 rounded-md bg-slate-100 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800">
            {(['little', 'big'] as const).map((e) => (
              <button
                key={e}
                type="button"
                onClick={() => setPackEndian(e)}
                className={`px-2.5 py-1 text-xs font-medium rounded cursor-pointer ${
                  packEndian === e
                    ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                    : 'text-slate-500'
                }`}
              >
                {e === 'little' ? 'LE' : 'BE'}
              </button>
            ))}
          </div>
        </div>

        {packedResult ? (
          <div className="space-y-2.5">
            {[
              { id: 'hex', label: 'Raw Hex Bytes', val: packedResult.hexSpaced },
              { id: 'py', label: 'Python Bytes Literal', val: packedResult.pythonLiteral },
              { id: 'dec', label: 'Unsigned Decimal', val: packedResult.decimal },
            ].map((row) => (
              <div
                key={row.id}
                className="p-3 rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3"
              >
                <div className="min-w-0">
                  <p className="text-[11px] text-slate-500">{row.label}</p>
                  <p className="text-xs font-mono text-slate-900 dark:text-slate-100 break-all mt-0.5">
                    {row.val}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void copyText(`pack-${row.id}`, row.val)}
                  className="shrink-0 text-xs text-amber-600 dark:text-amber-400 hover:underline cursor-pointer"
                >
                  {copiedId === `pack-${row.id}` ? 'Copied' : 'Copy'}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-red-600 dark:text-red-400">
            Enter a valid hexadecimal (0x...) or decimal integer.
          </p>
        )}
      </section>

      {/* 3. Multi-Format Encoding Workbench */}
      <section className="border border-slate-200 dark:border-slate-800 rounded-lg p-5 bg-white dark:bg-[#111827] space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Repeat className="w-4 h-4 text-amber-500" />
            <h2 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
              Encoding & Representation Converter
            </h2>
          </div>
          <span className="text-xs font-mono tabular-nums text-slate-500">
            {codecOutputs.byteLen} bytes
          </span>
        </div>

        <textarea
          rows={2}
          value={codecInput}
          onChange={(e) => setCodecInput(e.target.value)}
          placeholder="Enter ASCII, Base64, or text..."
          className="w-full p-2.5 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
        />

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          {[
            { id: 'c-hex', label: 'Hex (UTF-8)', val: codecOutputs.hex },
            { id: 'c-b64', label: 'Base64 Encode', val: codecOutputs.b64 },
            { id: 'c-b64d', label: 'Base64 Decode', val: codecOutputs.decodedB64 },
            { id: 'c-rot13', label: 'ROT-13', val: codecOutputs.rot13 },
          ].map((row) => (
            <div
              key={row.id}
              className="p-2.5 rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 space-y-1"
            >
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-500">{row.label}</span>
                <button
                  type="button"
                  onClick={() => void copyText(row.id, row.val)}
                  className="text-[11px] text-amber-600 dark:text-amber-400 hover:underline cursor-pointer"
                >
                  {copiedId === row.id ? 'Copied' : 'Copy'}
                </button>
              </div>
              <p className="text-xs font-mono text-slate-900 dark:text-slate-100 break-all">
                {row.val}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* 4. SHA-256 Flag Hasher & x86-64 Printf Stack Indexer */}
      <section className="border border-slate-200 dark:border-slate-800 rounded-lg p-5 bg-white dark:bg-[#111827] space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Hash className="w-4 h-4 text-amber-500" />
            <h2 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
              SHA-256 Flag Digest & Format Indexer
            </h2>
          </div>
          <span className="text-xs font-mono text-slate-500">WebCrypto · SysV</span>
        </div>

        <div className="space-y-2">
          <label className="block text-xs text-slate-600 dark:text-slate-400">
            Generate SHA-256 Flag Digest (for Organizer Challenge Authoring)
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={flagPlain}
              onChange={(e) => setFlagPlain(e.target.value)}
              className="flex-1 px-3 py-1.5 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
            />
            <button
              type="button"
              onClick={() => void computeFlagHash()}
              className="px-3.5 py-1.5 text-xs font-semibold rounded-md bg-amber-500 text-slate-950 hover:bg-amber-400 cursor-pointer whitespace-nowrap"
            >
              Hash Flag
            </button>
          </div>
          {flagDigest && (
            <div className="p-2.5 rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 flex items-center justify-between gap-2">
              <span className="text-[11px] font-mono text-emerald-600 dark:text-emerald-400 break-all">
                {flagDigest}
              </span>
              <button
                type="button"
                onClick={() => void copyText('sha', flagDigest)}
                className="shrink-0 text-xs text-amber-600 dark:text-amber-400 hover:underline cursor-pointer"
              >
                {copiedId === 'sha' ? 'Copied' : 'Copy'}
              </button>
            </div>
          )}
        </div>

        <div className="pt-3 border-t border-slate-200 dark:border-slate-800 space-y-2">
          <div className="flex items-center justify-between text-xs">
            <label htmlFor="fmt-arg-slider" className="text-slate-600 dark:text-slate-400">
              System V AMD64 printf Argument Parameter Index
            </label>
            <span className="font-mono tabular-nums text-slate-900 dark:text-slate-100">
              %{fmtArgIndex}$p
            </span>
          </div>
          <input
            id="fmt-arg-slider"
            type="range"
            min={1}
            max={24}
            value={fmtArgIndex}
            onChange={(e) => setFmtArgIndex(Number(e.target.value))}
            className="w-full accent-amber-500 cursor-pointer"
          />
          <p className="text-xs font-mono text-slate-700 dark:text-slate-300 bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 rounded p-2.5">
            Parameter #{fmtArgIndex} reads from: <span className="text-amber-600 dark:text-amber-400">{fmtStackLocation}</span>
          </p>
        </div>
      </section>
    </div>
  );
}
