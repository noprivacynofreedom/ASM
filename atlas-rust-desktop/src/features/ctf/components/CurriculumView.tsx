import React, { useEffect, useMemo, useState } from 'react';
import {
  Check,
  CheckCircle2,
  Copy,
  Download,
  FileArchive,
  Flag,
  Radio,
  Save,
  Search,
  Target,
  Users,
} from 'lucide-react';
import type {
  Challenge,
  ChallengeCategory,
  SwarmClaim,
  SwarmSharedNote,
  UserProgress,
} from '../types';
import { sha256Hex } from '../utils/ctfUtils';
import { StackFrameVisualizer } from './StackFrameVisualizer';

interface Props {
  challenges: Challenge[];
  selectedChallengeId: string | null;
  onSelectChallenge: (id: string) => void;
  progressMap: Record<string, UserProgress>;
  onSaveProgress: (params: {
    challenge: Challenge;
    status: 'unsolved' | 'in_progress' | 'solved';
    notes: string;
    pointsEarned: number;
  }) => Promise<void>;
  onOpenArchivePath: (zipPath: string) => void;
  swarmClaims: Record<string, SwarmClaim>;
  swarmSharedNotes: Record<string, SwarmSharedNote>;
  mySessionId: string;
  onToggleSwarmClaim: (challengeId: string) => void;
  onSyncSwarmNote: (challengeId: string, content: string) => void;
  onBroadcastFocus: (challengeId: string) => void;
  onAnnounceFlag: (challengeId: string, challengeTitle: string) => void;
}

const CATEGORIES: Array<'All' | ChallengeCategory> = [
  'All',
  'Reversing',
  'Stack',
  'ROP',
  'Format',
  'Heap',
];

export function CurriculumView({
  challenges,
  selectedChallengeId,
  onSelectChallenge,
  progressMap,
  onSaveProgress,
  onOpenArchivePath,
  swarmClaims,
  swarmSharedNotes,
  mySessionId,
  onToggleSwarmClaim,
  onSyncSwarmNote,
  onBroadcastFocus,
  onAnnounceFlag,
}: Props) {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<'All' | ChallengeCategory>('All');
  const [flagInput, setFlagInput] = useState('');
  const [flagFeedback, setFlagFeedback] = useState<{
    type: 'success' | 'error';
    message: string;
  } | null>(null);
  const [notesTab, setNotesTab] = useState<'personal' | 'swarm'>('personal');
  const [personalNotes, setPersonalNotes] = useState('');
  const [swarmNotesDraft, setSwarmNotesDraft] = useState('');
  const [savingNotes, setSavingNotes] = useState(false);
  const [copiedCode, setCopiedCode] = useState(false);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return challenges.filter((c) => {
      if (category !== 'All' && c.category !== category) return false;
      if (!q) return true;
      return (
        c.title.toLowerCase().includes(q) ||
        c.moduleName.toLowerCase().includes(q) ||
        c.moduleNum.toLowerCase().includes(q) ||
        c.category.toLowerCase().includes(q) ||
        c.zipPath.toLowerCase().includes(q)
      );
    });
  }, [challenges, search, category]);

  const activeChallenge = useMemo(
    () =>
      challenges.find((c) => c.id === selectedChallengeId) ||
      filtered[0] ||
      challenges[0] ||
      null,
    [challenges, filtered, selectedChallengeId]
  );

  const activeProgress = activeChallenge ? progressMap[activeChallenge.id] : undefined;
  const activeClaim = activeChallenge ? swarmClaims[activeChallenge.id] : undefined;
  const activeSwarmNote = activeChallenge ? swarmSharedNotes[activeChallenge.id] : undefined;

  useEffect(() => {
    if (!activeChallenge) return;
    setPersonalNotes(activeProgress?.notes ?? '');
    setFlagInput('');
    setFlagFeedback(null);
  }, [activeChallenge?.id, activeProgress?.notes]);

  useEffect(() => {
    if (!activeChallenge) return;
    setSwarmNotesDraft(activeSwarmNote?.content ?? '');
  }, [activeChallenge?.id, activeSwarmNote?.content]);

  const handleVerifyFlag = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeChallenge || !flagInput.trim()) return;
    const digest = await sha256Hex(flagInput.trim());
    if (digest === activeChallenge.flagHash.toLowerCase()) {
      await onSaveProgress({
        challenge: activeChallenge,
        status: 'solved',
        notes: personalNotes,
        pointsEarned: activeChallenge.points,
      });
      onAnnounceFlag(activeChallenge.id, activeChallenge.title);
      setFlagFeedback({
        type: 'success',
        message: `Flag verified (+${activeChallenge.points} pts). Solve recorded and announced to Swarm.`,
      });
    } else {
      setFlagFeedback({
        type: 'error',
        message: 'Digest mismatch. Inspect the Nightmare.zip lab binary or verify flag formatting.',
      });
    }
  };

  const handleSavePersonalNotes = async () => {
    if (!activeChallenge) return;
    setSavingNotes(true);
    try {
      const nextStatus =
        activeProgress?.status === 'solved' ? 'solved' : 'in_progress';
      await onSaveProgress({
        challenge: activeChallenge,
        status: nextStatus,
        notes: personalNotes,
        pointsEarned:
          activeProgress?.status === 'solved'
            ? activeProgress.pointsEarned
            : 0,
      });
    } finally {
      setSavingNotes(false);
    }
  };

  const handleCopyScript = async () => {
    if (!activeChallenge) return;
    await navigator.clipboard.writeText(activeChallenge.exploitTemplate);
    setCopiedCode(true);
    window.setTimeout(() => setCopiedCode(false), 1600);
  };

  const handleDownloadScript = () => {
    if (!activeChallenge) return;
    const blob = new Blob([activeChallenge.exploitTemplate], { type: 'text/x-python' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${activeChallenge.id}_analysis.py`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const solvedCount = useMemo(
    () =>
      challenges.filter((c) => progressMap[c.id]?.status === 'solved').length,
    [challenges, progressMap]
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
      {/* Left Pane: Nightmare Syllabus List */}
      <div className="lg:col-span-4 border border-slate-200 dark:border-slate-800 rounded-lg bg-white dark:bg-[#111827] overflow-hidden">
        <div className="p-4 border-b border-slate-200 dark:border-slate-800 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
              Nightmare Syllabus
            </h2>
            <span className="text-xs font-mono tabular-nums text-slate-500">
              {solvedCount}/{challenges.length} solved
            </span>
          </div>

          <div className="relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter modules, paths, or titles..."
              className="w-full pl-9 pr-3 py-1.5 text-sm rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
            />
          </div>

          <div className="flex items-center gap-1 overflow-x-auto pb-0.5">
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setCategory(cat)}
                className={`px-2.5 py-1 text-xs font-medium rounded transition-colors cursor-pointer whitespace-nowrap shrink-0 ${
                  category === cat
                    ? 'bg-slate-900 text-white dark:bg-amber-500 dark:text-slate-950'
                    : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        <div className="divide-y divide-slate-200 dark:divide-slate-800 max-h-[calc(100vh-290px)] overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="p-6 text-center text-sm text-slate-500">
              No modules match your filter.
            </div>
          ) : (
            filtered.map((item) => {
              const isSelected = activeChallenge?.id === item.id;
              const prog = progressMap[item.id];
              const claim = swarmClaims[item.id];
              const isSolved = prog?.status === 'solved';

              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onSelectChallenge(item.id)}
                  className={`w-full text-left px-4 py-3.5 transition-colors cursor-pointer block ${
                    isSelected
                      ? 'bg-amber-50/70 dark:bg-amber-500/10'
                      : 'hover:bg-slate-50 dark:hover:bg-slate-800/50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
                        {item.moduleNum}. {item.title}
                      </p>
                      <div className="flex flex-wrap items-center gap-1.5 mt-1 text-xs text-slate-500 dark:text-slate-400">
                        <span>{item.category}</span>
                        <span aria-hidden="true">·</span>
                        <span className="font-mono">{item.arch}</span>
                        <span aria-hidden="true">·</span>
                        <span className="font-mono tabular-nums">{item.points} pts</span>
                        {!item.published && (
                          <>
                            <span aria-hidden="true">·</span>
                            <span className="text-amber-600 dark:text-amber-400">Draft</span>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      {isSolved ? (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          Solved
                        </span>
                      ) : prog?.status === 'in_progress' ? (
                        <span className="text-xs text-amber-600 dark:text-amber-400">Active</span>
                      ) : (
                        <span className="text-xs text-slate-400">Open</span>
                      )}
                    </div>
                  </div>
                  {claim && (
                    <p className="mt-1.5 text-[11px] font-mono text-sky-600 dark:text-sky-400 truncate">
                      Swarm claim: @{claim.handle}
                    </p>
                  )}
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* Right Main Pane: Active Challenge Analysis & Learning Workspace */}
      <div className="lg:col-span-8 space-y-6">
        {!activeChallenge ? (
          <div className="border border-slate-200 dark:border-slate-800 rounded-lg p-10 text-center text-sm text-slate-500 bg-white dark:bg-[#111827]">
            Select a module from the Nightmare syllabus to begin analysis.
          </div>
        ) : (
          <>
            {/* Challenge Header & Quick Actions */}
            <div className="border border-slate-200 dark:border-slate-800 rounded-lg p-6 bg-white dark:bg-[#111827] space-y-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                    <span>Module {activeChallenge.moduleNum}</span>
                    <span aria-hidden="true">·</span>
                    <span>{activeChallenge.moduleName}</span>
                    <span aria-hidden="true">·</span>
                    <span>{activeChallenge.difficulty}</span>
                    <span aria-hidden="true">·</span>
                    <span className="font-mono tabular-nums">{activeChallenge.points} pts</span>
                  </div>
                  <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-slate-100">
                    {activeChallenge.title}
                  </h1>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onToggleSwarmClaim(activeChallenge.id)}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border transition-colors cursor-pointer whitespace-nowrap ${
                      activeClaim?.sessionId === mySessionId
                        ? 'border-sky-500 bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300'
                        : 'border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800'
                    }`}
                  >
                    <Target className="w-3.5 h-3.5" />
                    {activeClaim?.sessionId === mySessionId
                      ? 'Release Claim'
                      : activeClaim
                      ? `Claimed by @${activeClaim.handle}`
                      : 'Claim in Swarm'}
                  </button>
                  <button
                    type="button"
                    onClick={() => onBroadcastFocus(activeChallenge.id)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer whitespace-nowrap"
                  >
                    <Radio className="w-3.5 h-3.5" />
                    Focus Swarm
                  </button>
                  <button
                    type="button"
                    onClick={() => onOpenArchivePath(activeChallenge.zipPath)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-950 hover:opacity-90 transition-opacity cursor-pointer whitespace-nowrap"
                  >
                    <FileArchive className="w-3.5 h-3.5" />
                    Inspect in Archive
                  </button>
                </div>
              </div>

              <div className="space-y-3 text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                <p>{activeChallenge.summary}</p>
                <div className="p-3.5 rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 space-y-1">
                  <p className="text-xs font-semibold text-slate-900 dark:text-slate-100">
                    Lab Objective
                  </p>
                  <p className="text-xs text-slate-600 dark:text-slate-400">
                    {activeChallenge.objective}
                  </p>
                  <p className="text-xs font-mono text-slate-500 pt-1">
                    Archive Path: {activeChallenge.zipPath}
                  </p>
                </div>
              </div>

              {/* Binary Mitigations Row (Clean Tabular Grid, No Pills) */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2 border-t border-slate-200 dark:border-slate-800">
                {[
                  { label: 'NX Protection', value: activeChallenge.mitigations.nx },
                  { label: 'PIE', value: activeChallenge.mitigations.pie },
                  { label: 'Stack Canary', value: activeChallenge.mitigations.canary },
                  { label: 'RELRO', value: activeChallenge.mitigations.relro },
                ].map((m) => (
                  <div key={m.label} className="space-y-0.5">
                    <p className="text-xs text-slate-500">{m.label}</p>
                    <p className="text-sm font-mono font-medium text-slate-900 dark:text-slate-100">
                      {m.value}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* Interactive Educational Stack Visualizer */}
            <StackFrameVisualizer
              preset={activeChallenge.stackPreset}
              challengeTitle={activeChallenge.title}
            />

            {/* Flag Verification & Solve Persistence */}
            <div className="border border-slate-200 dark:border-slate-800 rounded-lg p-5 bg-white dark:bg-[#111827] space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Flag className="w-4 h-4 text-amber-500" />
                  <h3 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
                    Flag Verification
                  </h3>
                </div>
                <span className="text-xs text-slate-500">{activeChallenge.flagHint}</span>
              </div>

              <form onSubmit={handleVerifyFlag} className="flex flex-col sm:flex-row gap-2.5">
                <input
                  type="text"
                  value={flagInput}
                  onChange={(e) => setFlagInput(e.target.value)}
                  placeholder="atlas{...}"
                  className="flex-1 px-3.5 py-2 text-sm font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
                />
                <button
                  type="submit"
                  className="px-4 py-2 text-sm font-semibold rounded-md bg-amber-500 text-slate-950 hover:bg-amber-400 transition-colors cursor-pointer whitespace-nowrap"
                >
                  Verify Flag
                </button>
              </form>

              {flagFeedback && (
                <p
                  className={`text-xs font-medium ${
                    flagFeedback.type === 'success'
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-red-600 dark:text-red-400'
                  }`}
                >
                  {flagFeedback.message}
                </p>
              )}
            </div>

            {/* Dual Notes Workspace (Personal Firestore + Live Swarm Scratchpad) */}
            <div className="border border-slate-200 dark:border-slate-800 rounded-lg p-5 bg-white dark:bg-[#111827] space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-1 p-1 rounded-md bg-slate-100 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800">
                  <button
                    type="button"
                    onClick={() => setNotesTab('personal')}
                    className={`px-3 py-1 text-xs font-medium rounded transition-colors cursor-pointer whitespace-nowrap ${
                      notesTab === 'personal'
                        ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                        : 'text-slate-600 dark:text-slate-400'
                    }`}
                  >
                    Personal Notes
                  </button>
                  <button
                    type="button"
                    onClick={() => setNotesTab('swarm')}
                    className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded transition-colors cursor-pointer whitespace-nowrap ${
                      notesTab === 'swarm'
                        ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                        : 'text-slate-600 dark:text-slate-400'
                    }`}
                  >
                    <Users className="w-3.5 h-3.5" />
                    Swarm Shared Notes
                  </button>
                </div>

                {notesTab === 'personal' ? (
                  <button
                    type="button"
                    disabled={savingNotes}
                    onClick={() => void handleSavePersonalNotes()}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer whitespace-nowrap"
                  >
                    <Save className="w-3.5 h-3.5" />
                    {savingNotes ? 'Saving...' : 'Save to Cloud'}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => onSyncSwarmNote(activeChallenge.id, swarmNotesDraft)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer whitespace-nowrap"
                  >
                    <Radio className="w-3.5 h-3.5" />
                    Sync to Swarm Room
                  </button>
                )}
              </div>

              {notesTab === 'personal' ? (
                <textarea
                  rows={4}
                  maxLength={4000}
                  value={personalNotes}
                  onChange={(e) => setPersonalNotes(e.target.value)}
                  placeholder="Record binary offsets, symbol addresses, mitigation findings, and disassembly notes..."
                  className="w-full p-3 text-sm font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
                />
              ) : (
                <div className="space-y-1.5">
                  <textarea
                    rows={4}
                    maxLength={4000}
                    value={swarmNotesDraft}
                    onChange={(e) => setSwarmNotesDraft(e.target.value)}
                    placeholder="Collaborate on shared offsets, findings, and binary observations with other active Swarm sessions..."
                    className="w-full p-3 text-sm font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
                  />
                  {activeSwarmNote && (
                    <p className="text-xs text-slate-500">
                      Last synced by <span className="font-mono">@{activeSwarmNote.updatedBy}</span>{' '}
                      at {new Date(activeSwarmNote.updatedAt).toLocaleTimeString()}
                    </p>
                  )}
                </div>
              )}
            </div>

            {/* Reference Analysis Script */}
            <div className="border border-slate-200 dark:border-slate-800 rounded-lg overflow-hidden bg-white dark:bg-[#111827]">
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-800">
                <h3 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
                  Reference Analysis Script
                </h3>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void handleCopyScript()}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer"
                  >
                    {copiedCode ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                    {copiedCode ? 'Copied' : 'Copy'}
                  </button>
                  <button
                    type="button"
                    onClick={handleDownloadScript}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Download .py
                  </button>
                </div>
              </div>
              <pre className="p-4 text-xs font-mono leading-relaxed overflow-x-auto bg-slate-950 text-slate-200">
                <code>{activeChallenge.exploitTemplate}</code>
              </pre>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
