import React, { useEffect, useMemo, useState } from 'react';
import {
  Binary,
  Check,
  Copy,
  Download,
  FileArchive,
  FileCode2,
  Folder,
  Radio,
  Search,
  Upload,
} from 'lucide-react';
import type { SwarmArchiveManifest, ZipEntryItem } from '../types';
import {
  extractAsciiStrings,
  formatHexDump,
  parseElfHeader,
} from '../utils/ctfUtils';

interface Props {
  archiveName: string;
  entries: ZipEntryItem[];
  selectedPath: string | null;
  onSelectPath: (path: string) => void;
  onImportZipFile: (file: File) => Promise<void>;
  onLoadStarterArchive: () => Promise<void>;
  onDownloadCurrentArchive: () => void;
  onSyncManifestToSwarm: () => void;
  swarmManifest: SwarmArchiveManifest | null;
}

export function ArchiveExplorerView({
  archiveName,
  entries,
  selectedPath,
  onSelectPath,
  onImportZipFile,
  onLoadStarterArchive,
  onDownloadCurrentArchive,
  onSyncManifestToSwarm,
  swarmManifest,
}: Props) {
  const [treeFilter, setTreeFilter] = useState('');
  const [inspectorTab, setInspectorTab] = useState<'source' | 'elf' | 'strings' | 'hex'>('source');
  const [minStrLen, setMinStrLen] = useState(5);
  const [strQuery, setStrQuery] = useState('');
  const [hexOffset, setHexOffset] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const fileEntries = useMemo(() => {
    const q = treeFilter.trim().toLowerCase();
    return entries.filter((e) => !q || e.path.toLowerCase().includes(q));
  }, [entries, treeFilter]);

  const activeEntry = useMemo(
    () =>
      entries.find((e) => e.path === selectedPath && !e.dir) ||
      entries.find((e) => !e.dir) ||
      null,
    [entries, selectedPath]
  );

  useEffect(() => {
    setHexOffset(0);
    if (!activeEntry) return;
    if (activeEntry.isElf) {
      setInspectorTab('elf');
    } else if (activeEntry.text !== undefined) {
      setInspectorTab('source');
    } else {
      setInspectorTab('hex');
    }
  }, [activeEntry?.path]);

  const elfInfo = useMemo(
    () => (activeEntry?.bytes && activeEntry.isElf ? parseElfHeader(activeEntry.bytes) : null),
    [activeEntry]
  );

  const extractedStrings = useMemo(() => {
    if (!activeEntry?.bytes) return [];
    const list = extractAsciiStrings(activeEntry.bytes, minStrLen, 400);
    const q = strQuery.trim().toLowerCase();
    return q ? list.filter((item) => item.value.toLowerCase().includes(q)) : list;
  }, [activeEntry, minStrLen, strQuery]);

  const hexRows = useMemo(() => {
    if (!activeEntry?.bytes) return [];
    return formatHexDump(activeEntry.bytes, hexOffset, 512);
  }, [activeEntry, hexOffset]);

  const copyValue = async (key: string, val: string) => {
    await navigator.clipboard.writeText(val);
    setCopiedKey(key);
    window.setTimeout(() => setCopiedKey(null), 1500);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      await onImportZipFile(file);
    }
  };

  const totalFiles = entries.filter((e) => !e.dir).length;
  const totalBytes = entries.reduce((sum, e) => sum + e.size, 0);

  return (
    <div className="space-y-6">
      {/* Dropzone & Archive Toolbar */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => void handleDrop(e)}
        className={`border rounded-lg p-5 transition-colors bg-white dark:bg-[#111827] flex flex-wrap items-center justify-between gap-4 ${
          dragging
            ? 'border-amber-500 bg-amber-50/40 dark:bg-amber-500/10'
            : 'border-slate-200 dark:border-slate-800'
        }`}
      >
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
            <FileArchive className="w-4 h-4 text-amber-500" />
            <h2 className="text-base font-semibold font-display">{archiveName}</h2>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 font-mono tabular-nums">
            {totalFiles} files · {(totalBytes / 1024).toFixed(1)} KB extracted client-side · Drop any
            Nightmare.zip here to replace
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <label className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-md bg-amber-500 text-slate-950 hover:bg-amber-400 transition-colors cursor-pointer whitespace-nowrap">
            <Upload className="w-3.5 h-3.5" />
            Upload .zip
            <input
              type="file"
              accept=".zip"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void onImportZipFile(f);
                e.target.value = '';
              }}
            />
          </label>
          <button
            type="button"
            onClick={() => void onLoadStarterArchive()}
            className="px-3.5 py-2 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer whitespace-nowrap"
          >
            Reset Starter Archive
          </button>
          <button
            type="button"
            onClick={onDownloadCurrentArchive}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer whitespace-nowrap"
          >
            <Download className="w-3.5 h-3.5" />
            Download Zip
          </button>
          <button
            type="button"
            onClick={onSyncManifestToSwarm}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer whitespace-nowrap"
          >
            <Radio className="w-3.5 h-3.5" />
            Sync Manifest to Swarm
          </button>
        </div>
      </div>

      {swarmManifest && (
        <div className="px-4 py-2.5 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-100/70 dark:bg-[#0F172A] text-xs text-slate-600 dark:text-slate-400 flex flex-wrap items-center justify-between gap-2">
          <span>
            Swarm room synced archive:{' '}
            <span className="font-mono text-slate-900 dark:text-slate-200">
              {swarmManifest.fileName}
            </span>{' '}
            ({swarmManifest.fileCount} files shared by{' '}
            <span className="font-mono">@{swarmManifest.sharedBy}</span>)
          </span>
          <span className="font-mono tabular-nums">
            {new Date(swarmManifest.sharedAt).toLocaleTimeString()}
          </span>
        </div>
      )}

      {/* Split Explorer & Inspector */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Directory Tree */}
        <div className="lg:col-span-4 border border-slate-200 dark:border-slate-800 rounded-lg bg-white dark:bg-[#111827] overflow-hidden">
          <div className="p-3.5 border-b border-slate-200 dark:border-slate-800">
            <div className="relative">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={treeFilter}
                onChange={(e) => setTreeFilter(e.target.value)}
                placeholder="Search archive paths..."
                className="w-full pl-9 pr-3 py-1.5 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
              />
            </div>
          </div>

          <div className="divide-y divide-slate-100 dark:divide-slate-800/70 max-h-[560px] overflow-y-auto">
            {fileEntries.map((entry) => {
              const depth = Math.max(0, entry.path.replace(/\/$/, '').split('/').length - 1);
              if (entry.dir) {
                return (
                  <div
                    key={entry.path}
                    style={{ paddingLeft: `${12 + depth * 12}px` }}
                    className="pr-3 py-2 flex items-center gap-2 text-xs text-slate-500 bg-slate-50/50 dark:bg-slate-900/30"
                  >
                    <Folder className="w-3.5 h-3.5 shrink-0 text-amber-500/80" />
                    <span className="font-mono truncate">{entry.name}/</span>
                  </div>
                );
              }
              const isSelected = activeEntry?.path === entry.path;
              return (
                <button
                  key={entry.path}
                  type="button"
                  onClick={() => onSelectPath(entry.path)}
                  style={{ paddingLeft: `${12 + depth * 12}px` }}
                  className={`w-full pr-3 py-2.5 flex items-center justify-between gap-2 text-left text-xs transition-colors cursor-pointer ${
                    isSelected
                      ? 'bg-amber-50 dark:bg-amber-500/10 text-slate-950 dark:text-slate-100'
                      : 'text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/60'
                  }`}
                >
                  <span className="flex items-center gap-2 min-w-0">
                    {entry.isElf ? (
                      <Binary className="w-3.5 h-3.5 shrink-0 text-emerald-500" />
                    ) : (
                      <FileCode2 className="w-3.5 h-3.5 shrink-0 text-slate-400" />
                    )}
                    <span className="font-mono truncate">{entry.name}</span>
                  </span>
                  <span className="shrink-0 font-mono tabular-nums text-[11px] text-slate-500">
                    {entry.isElf ? `ELF · ${entry.size} B` : `${entry.size} B`}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Binary / File Inspector */}
        <div className="lg:col-span-8 border border-slate-200 dark:border-slate-800 rounded-lg bg-white dark:bg-[#111827] overflow-hidden">
          {!activeEntry ? (
            <div className="p-10 text-center text-sm text-slate-500">
              Select a file from the archive tree to inspect its contents, ELF headers, strings, or
              hex bytes.
            </div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs font-mono text-slate-900 dark:text-slate-100 truncate">
                    {activeEntry.path}
                  </p>
                  <p className="text-[11px] font-mono tabular-nums text-slate-500">
                    {activeEntry.size} bytes · {activeEntry.isElf ? 'ELF Binary' : 'Text / Raw File'}
                  </p>
                </div>

                <div className="flex items-center gap-1 p-1 rounded-md bg-slate-100 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800">
                  {activeEntry.text !== undefined && (
                    <button
                      type="button"
                      onClick={() => setInspectorTab('source')}
                      className={`px-2.5 py-1 text-xs font-medium rounded cursor-pointer whitespace-nowrap ${
                        inspectorTab === 'source'
                          ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                          : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                      }`}
                    >
                      Source
                    </button>
                  )}
                  {activeEntry.isElf && (
                    <button
                      type="button"
                      onClick={() => setInspectorTab('elf')}
                      className={`px-2.5 py-1 text-xs font-medium rounded cursor-pointer whitespace-nowrap ${
                        inspectorTab === 'elf'
                          ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                          : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                      }`}
                    >
                      ELF & Checksec
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setInspectorTab('strings')}
                    className={`px-2.5 py-1 text-xs font-medium rounded cursor-pointer whitespace-nowrap ${
                      inspectorTab === 'strings'
                        ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                        : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                    }`}
                  >
                    Strings
                  </button>
                  <button
                    type="button"
                    onClick={() => setInspectorTab('hex')}
                    className={`px-2.5 py-1 text-xs font-medium rounded cursor-pointer whitespace-nowrap ${
                      inspectorTab === 'hex'
                        ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                        : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                    }`}
                  >
                    Hex Dump
                  </button>
                </div>
              </div>

              {/* Tab Content */}
              {inspectorTab === 'source' && activeEntry.text !== undefined && (
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => void copyValue('src', activeEntry.text || '')}
                    className="absolute right-3 top-3 inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded bg-slate-800 text-slate-200 hover:bg-slate-700 cursor-pointer"
                  >
                    {copiedKey === 'src' ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                    {copiedKey === 'src' ? 'Copied' : 'Copy'}
                  </button>
                  <pre className="p-4 text-xs font-mono leading-relaxed overflow-auto max-h-[520px] bg-slate-950 text-slate-200">
                    <code>{activeEntry.text}</code>
                  </pre>
                </div>
              )}

              {inspectorTab === 'elf' && elfInfo && (
                <div className="p-5 space-y-5">
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                    {[
                      { k: 'Class', v: elfInfo.bitness },
                      { k: 'Endianness', v: elfInfo.endianness },
                      { k: 'Architecture', v: elfInfo.machine },
                      { k: 'ELF Type', v: elfInfo.type },
                      { k: 'Entry Point', v: elfInfo.entryPoint },
                      {
                        k: 'Headers (PH / SH)',
                        v: `${elfInfo.programHeaderCount} / ${elfInfo.sectionHeaderCount}`,
                      },
                    ].map((row) => (
                      <div
                        key={row.k}
                        className="p-3 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-[#0B1120]"
                      >
                        <p className="text-xs text-slate-500">{row.k}</p>
                        <p className="text-sm font-mono font-medium text-slate-900 dark:text-slate-100 mt-0.5">
                          {row.v}
                        </p>
                      </div>
                    ))}
                  </div>

                  <div className="space-y-2 pt-3 border-t border-slate-200 dark:border-slate-800">
                    <h4 className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                      Parsed Program Header Security Mitigations (Checksec)
                    </h4>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      <div className="p-3 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-[#0B1120] flex items-center justify-between text-xs">
                        <span className="text-slate-500">NX (PT_GNU_STACK)</span>
                        <span
                          className={`font-mono font-semibold ${
                            elfInfo.nx === 'Enabled'
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : 'text-amber-600 dark:text-amber-400'
                          }`}
                        >
                          {elfInfo.nx}
                        </span>
                      </div>
                      <div className="p-3 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-[#0B1120] flex items-center justify-between text-xs">
                        <span className="text-slate-500">PIE (ET_DYN)</span>
                        <span
                          className={`font-mono font-semibold ${
                            elfInfo.pie === 'Enabled'
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : 'text-amber-600 dark:text-amber-400'
                          }`}
                        >
                          {elfInfo.pie}
                        </span>
                      </div>
                      <div className="p-3 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-[#0B1120] flex items-center justify-between text-xs">
                        <span className="text-slate-500">RELRO</span>
                        <span
                          className={`font-mono font-semibold ${
                            elfInfo.relro !== 'No RELRO'
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : 'text-amber-600 dark:text-amber-400'
                          }`}
                        >
                          {elfInfo.relro}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {inspectorTab === 'strings' && (
                <div className="p-4 space-y-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <input
                      type="text"
                      value={strQuery}
                      onChange={(e) => setStrQuery(e.target.value)}
                      placeholder="Filter extracted strings (e.g. atlas{)..."
                      className="flex-1 min-w-[200px] px-3 py-1.5 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-100"
                    />
                    <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-400">
                      Min length:
                      <input
                        type="number"
                        min={3}
                        max={24}
                        value={minStrLen}
                        onChange={(e) => setMinStrLen(Math.max(3, Number(e.target.value) || 4))}
                        className="w-16 px-2 py-1 text-xs font-mono tabular-nums rounded bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-100"
                      />
                    </label>
                  </div>

                  <div className="border border-slate-200 dark:border-slate-800 rounded-md overflow-hidden max-h-[420px] overflow-y-auto">
                    <table className="w-full text-xs font-mono">
                      <thead className="bg-slate-50 dark:bg-[#0B1120] text-slate-500 border-b border-slate-200 dark:border-slate-800">
                        <tr>
                          <th className="text-left px-3 py-2 font-medium w-28">Offset</th>
                          <th className="text-left px-3 py-2 font-medium">Printable String</th>
                          <th className="text-right px-3 py-2 font-medium w-20">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
                        {extractedStrings.length === 0 ? (
                          <tr>
                            <td colSpan={3} className="px-3 py-6 text-center text-slate-500">
                              No strings matched.
                            </td>
                          </tr>
                        ) : (
                          extractedStrings.map((s) => (
                            <tr
                              key={`${s.offset}-${s.value}`}
                              className="hover:bg-slate-50 dark:hover:bg-slate-800/40"
                            >
                              <td className="px-3 py-2 text-slate-500 tabular-nums">{s.offset}</td>
                              <td className="px-3 py-2 text-slate-900 dark:text-slate-100 break-all">
                                {s.value}
                              </td>
                              <td className="px-3 py-2 text-right">
                                <button
                                  type="button"
                                  onClick={() => void copyValue(s.offset, s.value)}
                                  className="text-amber-600 dark:text-amber-400 hover:underline cursor-pointer"
                                >
                                  {copiedKey === s.offset ? 'Copied' : 'Copy'}
                                </button>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {inspectorTab === 'hex' && (
                <div className="p-4 space-y-3">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-mono tabular-nums text-slate-500">
                      Showing bytes 0x{hexOffset.toString(16)}–0x
                      {Math.min(activeEntry.size, hexOffset + 512).toString(16)} of{' '}
                      {activeEntry.size}
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        disabled={hexOffset === 0}
                        onClick={() => setHexOffset((o) => Math.max(0, o - 512))}
                        className="px-2.5 py-1 rounded border border-slate-300 dark:border-slate-700 disabled:opacity-40 cursor-pointer"
                      >
                        Prev 512B
                      </button>
                      <button
                        type="button"
                        disabled={hexOffset + 512 >= activeEntry.size}
                        onClick={() => setHexOffset((o) => o + 512)}
                        className="px-2.5 py-1 rounded border border-slate-300 dark:border-slate-700 disabled:opacity-40 cursor-pointer"
                      >
                        Next 512B
                      </button>
                    </div>
                  </div>
                  <div className="rounded-md bg-slate-950 text-slate-200 p-3.5 overflow-x-auto font-mono text-xs leading-5 max-h-[430px] overflow-y-auto">
                    {hexRows.map((row) => (
                      <div key={row.offset} className="whitespace-pre flex gap-4">
                        <span className="text-slate-500 select-none">{row.offset}</span>
                        <span className="text-amber-300/90">{row.hexLeft}</span>
                        <span className="text-sky-300/90">{row.hexRight}</span>
                        <span className="text-slate-300 border-l border-slate-800 pl-3">
                          {row.ascii}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
