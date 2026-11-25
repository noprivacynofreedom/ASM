import React, { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, RotateCcw, ShieldCheck } from 'lucide-react';
import type { StackSimulationPreset } from '../types';

interface Props {
  preset?: StackSimulationPreset;
  challengeTitle: string;
}

export function StackFrameVisualizer({ preset, challengeTitle }: Props) {
  const bufSize = preset?.bufSize ?? 32;
  const targetSymbol = preset?.targetSymbol ?? 'target_fn';
  const targetAddr = preset?.targetAddr ?? '0x00401196';

  const [inputBytes, setInputBytes] = useState<number>(Math.min(16, bufSize));
  const [canaryEnabled, setCanaryEnabled] = useState<boolean>(false);

  useEffect(() => {
    setInputBytes(Math.min(16, bufSize));
  }, [bufSize, challengeTitle]);

  const canarySize = canaryEnabled ? 8 : 0;
  const rbpStart = bufSize + canarySize;
  const ripStart = rbpStart + 8;
  const maxBytes = ripStart + 16;

  const bufFill = Math.min(inputBytes, bufSize);
  const canaryFill = canaryEnabled ? Math.max(0, Math.min(inputBytes - bufSize, 8)) : 0;
  const rbpFill = Math.max(0, Math.min(inputBytes - rbpStart, 8));
  const ripFill = Math.max(0, Math.min(inputBytes - ripStart, 8));

  const state =
    canaryFill > 0
      ? {
          label: 'CANARY TRIPPED (SIGABRT)',
          tone: 'text-amber-600 dark:text-amber-400',
          detail:
            'Stack protector detected guard word modification before function return; execution safely aborted.',
        }
      : ripFill > 0
      ? {
          label: 'SAVED RIP BOUNDARY CROSSED',
          tone: 'text-red-600 dark:text-red-400',
          detail: `Write reached offset +0x${ripStart.toString(16)} (${ripStart} bytes), overwriting the saved return pointer (${targetSymbol} @ ${targetAddr}).`,
        }
      : rbpFill > 0
      ? {
          label: 'SAVED RBP CORRUPTED',
          tone: 'text-amber-600 dark:text-amber-400',
          detail: `Input exceeded ${bufSize}-byte buffer and spilled ${rbpFill} byte(s) into Saved RBP.`,
        }
      : {
          label: 'NOMINAL BOUNDS',
          tone: 'text-emerald-600 dark:text-emerald-400',
          detail: `Input (${inputBytes} / ${bufSize} bytes) remains safely inside allocated stack buffer.`,
        };

  const segments = [
    {
      name: 'Local Buffer',
      offset: '0x00',
      size: bufSize,
      filled: bufFill,
      baseClass: 'bg-slate-200 dark:bg-slate-800',
      fillClass: 'bg-sky-600 dark:bg-sky-500',
    },
    ...(canaryEnabled
      ? [
          {
            name: 'Stack Canary',
            offset: `0x${bufSize.toString(16).padStart(2, '0')}`,
            size: 8,
            filled: canaryFill,
            baseClass: 'bg-emerald-100 dark:bg-emerald-950/60',
            fillClass: 'bg-amber-500',
          },
        ]
      : []),
    {
      name: 'Saved RBP',
      offset: `0x${rbpStart.toString(16).padStart(2, '0')}`,
      size: 8,
      filled: rbpFill,
      baseClass: 'bg-slate-200 dark:bg-slate-800',
      fillClass: 'bg-amber-500',
    },
    {
      name: 'Saved RIP',
      offset: `0x${ripStart.toString(16).padStart(2, '0')}`,
      size: 8,
      filled: ripFill,
      baseClass: 'bg-slate-200 dark:bg-slate-800',
      fillClass: 'bg-red-600 dark:bg-red-500',
    },
  ];

  return (
    <div className="border border-slate-200 dark:border-slate-800 rounded-lg p-5 bg-white dark:bg-[#111827] space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
            Interactive Stack Frame Layout
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Low memory (RSP) on left to higher addresses (Saved RIP) on right.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setCanaryEnabled((v) => !v)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border transition-colors cursor-pointer whitespace-nowrap ${
              canaryEnabled
                ? 'border-emerald-500/60 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300'
                : 'border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            Stack Canary: {canaryEnabled ? 'On' : 'Off'}
          </button>
          <button
            type="button"
            onClick={() => setInputBytes(Math.min(16, bufSize))}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer whitespace-nowrap"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Reset
          </button>
        </div>
      </div>

      {/* Interactive Slider */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <label
            htmlFor="stack-bytes-slider"
            className="font-medium text-slate-700 dark:text-slate-300"
          >
            Simulated Input Write Length
          </label>
          <span className="font-mono tabular-nums text-slate-900 dark:text-slate-100">
            {inputBytes} bytes (0x{inputBytes.toString(16).padStart(2, '0')})
          </span>
        </div>
        <input
          id="stack-bytes-slider"
          type="range"
          min={0}
          max={maxBytes}
          value={inputBytes}
          onChange={(e) => setInputBytes(Number(e.target.value))}
          className="w-full accent-amber-500 cursor-pointer"
        />
        <div className="flex justify-between text-[11px] font-mono tabular-nums text-slate-500">
          <span>0 B</span>
          <span>Buffer End: {bufSize} B</span>
          <span>RIP Offset: {ripStart} B</span>
          <span>{maxBytes} B</span>
        </div>
      </div>

      {/* Memory Regions Bar */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-1">
        {segments.map((seg) => {
          const pct = Math.round((seg.filled / seg.size) * 100);
          return (
            <div
              key={seg.name}
              className="border border-slate-200 dark:border-slate-800 rounded-md p-3 bg-slate-50 dark:bg-[#0B1120] space-y-2"
            >
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-slate-800 dark:text-slate-200">{seg.name}</span>
                <span className="font-mono text-slate-500">+{seg.offset}</span>
              </div>
              <div className={`h-2.5 w-full rounded-sm overflow-hidden ${seg.baseClass}`}>
                <div
                  className={`h-full transition-all duration-150 ${seg.fillClass}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-[11px] font-mono tabular-nums text-slate-500">
                <span>
                  {seg.filled}/{seg.size} B
                </span>
                <span>{pct}%</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Explicit Dual-Coded Status Callout */}
      <div className="flex items-start gap-2.5 pt-2 border-t border-slate-200 dark:border-slate-800 text-xs">
        {canaryFill === 0 && ripFill === 0 && rbpFill === 0 ? (
          <CheckCircle2 className={`w-4 h-4 shrink-0 mt-0.5 ${state.tone}`} />
        ) : (
          <AlertTriangle className={`w-4 h-4 shrink-0 mt-0.5 ${state.tone}`} />
        )}
        <div className="space-y-0.5">
          <p className={`font-semibold font-mono ${state.tone}`}>{state.label}</p>
          <p className="text-slate-600 dark:text-slate-400 leading-relaxed">{state.detail}</p>
        </div>
      </div>
    </div>
  );
}
