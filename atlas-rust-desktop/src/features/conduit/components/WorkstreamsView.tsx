import { FormEvent, useMemo, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  FileCode2,
  GitCommitHorizontal,
  GitMerge,
  Plus,
  Search,
  X,
} from 'lucide-react';
import {
  OrchestratorState,
  ProviderSource,
  ResolutionStrategy,
  Workstream,
} from '../types/orchestrator';
import { filterWorkstreams, ReadinessSummary } from '../utils/orchestrator';

interface WorkstreamsViewProps {
  state: OrchestratorState;
  readiness: ReadinessSummary;
  onCommitWorkstream: (id: string) => void;
  onCommitAllUncommitted: () => void;
  onResolveConflict: (id: string, strategy: ResolutionStrategy) => void;
  onToggleSelection: (id: string) => void;
  onAddWorkstream: (input: {
    title: string;
    branch: string;
    provider: ProviderSource;
    gitState: 'committed' | 'uncommitted';
    summary: string;
    filePath: string;
  }) => void;
  onBuildBundle: () => void;
}

const PROVIDER_LABELS: Record<ProviderSource, string> = {
  google: 'Google Chat / Gemini',
  chatgpt: 'ChatGPT',
  local: 'Local Git / Ollama',
};

export function WorkstreamsView({
  state,
  readiness,
  onCommitWorkstream,
  onCommitAllUncommitted,
  onResolveConflict,
  onToggleSelection,
  onAddWorkstream,
  onBuildBundle,
}: WorkstreamsViewProps) {
  const [providerFilter, setProviderFilter] = useState<ProviderSource | 'all'>('all');
  const [gitFilter, setGitFilter] = useState<'all' | 'committed' | 'uncommitted' | 'conflict'>('all');
  const [query, setQuery] = useState('');
  const [inspectedId, setInspectedId] = useState<string>(state.workstreams[0]?.id ?? '');
  const [strategyChoice, setStrategyChoice] = useState<ResolutionStrategy>('merged');
  const [showAddModal, setShowAddModal] = useState(false);

  // Add Workstream form state
  const [formTitle, setFormTitle] = useState('');
  const [formBranch, setFormBranch] = useState('');
  const [formProvider, setFormProvider] = useState<ProviderSource>('local');
  const [formGitState, setFormGitState] = useState<'committed' | 'uncommitted'>('uncommitted');
  const [formFilePath, setFormFilePath] = useState('');
  const [formSummary, setFormSummary] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const filtered = useMemo(
    () =>
      filterWorkstreams(state.workstreams, {
        provider: providerFilter,
        gitState: gitFilter,
        query,
      }),
    [state.workstreams, providerFilter, gitFilter, query]
  );

  const inspected: Workstream | undefined =
    state.workstreams.find((w) => w.id === inspectedId) ?? filtered[0] ?? state.workstreams[0];

  const handleCreateWorkstream = (e: FormEvent) => {
    e.preventDefault();
    if (!formTitle.trim() || !formBranch.trim()) {
      setFormError('Title and Git branch name are required.');
      return;
    }
    onAddWorkstream({
      title: formTitle,
      branch: formBranch,
      provider: formProvider,
      gitState: formGitState,
      filePath: formFilePath,
      summary: formSummary || 'Registered workstream for atlas-chat integration.',
    });
    setFormTitle('');
    setFormBranch('');
    setFormFilePath('');
    setFormSummary('');
    setFormError(null);
    setShowAddModal(false);
  };

  return (
    <div className="mx-auto max-w-[1280px] space-y-6">
      {/* Header */}
      <div className="flex flex-col justify-between gap-4 border-b border-[#20242E] pb-5 xl:flex-row xl:items-end">
        <div className="max-w-xl">
          <h1 className="text-[22px] font-semibold tracking-tight text-[#F9FAFB]">
            Workstreams & Git Staging
          </h1>
          <p className="mt-1 text-[13.5px] text-[#9CA3AF]">
            Stage untracked paths, resolve provider merge conflicts, and consolidate all branches into{' '}
            <span className="font-mono text-[#D1D5DB]">{state.bundle.targetBranch}</span>.
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2.5 xl:flex-nowrap">
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[#2C3240] bg-[#171B24] px-3.5 py-2 text-[13px] font-medium text-[#E5E7EB] transition-colors hover:bg-[#1E232F] whitespace-nowrap shrink-0"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            <span>Register Stream</span>
          </button>

          {readiness.uncommittedCount > 0 && (
            <button
              type="button"
              onClick={onCommitAllUncommitted}
              className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3.5 py-2 text-[13px] font-medium text-amber-300 transition-colors hover:bg-amber-500/20 whitespace-nowrap shrink-0"
            >
              <GitCommitHorizontal className="h-4 w-4" aria-hidden="true" />
              <span>Commit All Uncommitted ({readiness.uncommittedCount})</span>
            </button>
          )}

          <button
            type="button"
            onClick={onBuildBundle}
            disabled={!readiness.canConsolidate}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-[13px] font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:border disabled:border-[#323A4E] disabled:bg-[#1B202C] disabled:text-[#9CA3AF] whitespace-nowrap shrink-0"
          >
            <GitMerge className="h-4 w-4" aria-hidden="true" />
            <span>Build Integration Bundle</span>
          </button>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          {/* Provider segmented filter */}
          <div className="inline-flex items-center rounded-lg border border-[#222630] bg-[#14171D] p-1" role="group" aria-label="Filter by provider">
            {(['all', 'google', 'chatgpt', 'local'] as const).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setProviderFilter(p)}
                className={`rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors whitespace-nowrap ${
                  providerFilter === p
                    ? 'bg-[#222836] text-[#F9FAFB]'
                    : 'text-[#8B92A5] hover:text-[#E5E7EB]'
                }`}
              >
                {p === 'all' ? 'All Providers' : p === 'google' ? 'Google' : p === 'chatgpt' ? 'ChatGPT' : 'Local'}
              </button>
            ))}
          </div>

          {/* Git state segmented filter */}
          <div className="inline-flex items-center rounded-lg border border-[#222630] bg-[#14171D] p-1" role="group" aria-label="Filter by git state">
            {(['all', 'committed', 'uncommitted', 'conflict'] as const).map((g) => (
              <button
                key={g}
                type="button"
                onClick={() => setGitFilter(g)}
                className={`rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors whitespace-nowrap ${
                  gitFilter === g
                    ? 'bg-[#222836] text-[#F9FAFB]'
                    : 'text-[#8B92A5] hover:text-[#E5E7EB]'
                }`}
              >
                {g === 'all'
                  ? 'All States'
                  : g === 'committed'
                    ? 'Committed'
                    : g === 'uncommitted'
                      ? 'Uncommitted'
                      : 'Conflicts'}
              </button>
            ))}
          </div>
        </div>

        <div className="relative w-full lg:w-72">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#6B7280]"
            aria-hidden="true"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter branches or files..."
            aria-label="Filter workstreams by branch or file"
            className="w-full rounded-lg border border-[#242936] bg-[#14171D] py-2 pl-9 pr-3 text-[13px] text-[#F3F4F6] placeholder-[#6B7280] focus:border-blue-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Main Split: Workstreams Table + Diff / Conflict Inspector */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <div className="rounded-xl border border-[#222630] bg-[#14171D] xl:col-span-7 overflow-hidden">
          {filtered.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <p className="text-[14px] font-medium text-[#E5E7EB]">
                No matching workstreams found
              </p>
              <p className="mt-1 text-[13px] text-[#8B92A5]">
                Clear your search or filter selection to inspect all atlas-chat branches.
              </p>
              <button
                type="button"
                onClick={() => {
                  setProviderFilter('all');
                  setGitFilter('all');
                  setQuery('');
                }}
                className="mt-4 rounded-lg border border-[#2C3240] bg-[#1B1F2A] px-3.5 py-2 text-[13px] font-medium text-[#E5E7EB] hover:bg-[#242A38]"
              >
                Reset Filters
              </button>
            </div>
          ) : (
            <div className="divide-y divide-[#1E222C]">
              {filtered.map((ws) => {
                const isSelectedRow = inspected?.id === ws.id;
                const additions = ws.files.reduce((s, f) => s + f.additions, 0);
                const deletions = ws.files.reduce((s, f) => s + f.deletions, 0);

                return (
                  <div
                    key={ws.id}
                    className={`flex items-start gap-3.5 px-5 py-4 transition-colors ${
                      isSelectedRow ? 'bg-[#191E28]' : 'hover:bg-[#171B23]'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={ws.selectedForIntegration}
                      onChange={() => onToggleSelection(ws.id)}
                      aria-label={`Include ${ws.branch} in integration bundle`}
                      className="mt-1 h-4 w-4 rounded border-[#363C4E] bg-[#0D0F13] accent-blue-500"
                    />

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => setInspectedId(ws.id)}
                          className="text-left text-[14px] font-medium text-[#F3F4F6] hover:text-blue-300 focus-visible:outline-none focus-visible:underline"
                        >
                          {ws.title}
                        </button>

                        <div className="flex items-center gap-2 shrink-0">
                          {ws.conflictState === 'conflict' ? (
                            <span className="inline-flex items-center gap-1 text-[12px] font-medium text-[#EF4444]">
                              <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
                              Conflict
                            </span>
                          ) : ws.gitState === 'uncommitted' ? (
                            <span className="inline-flex items-center gap-1 text-[12px] font-medium text-[#F59E0B]">
                              <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                              Uncommitted
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-[12px] font-medium text-[#22C55E]">
                              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                              Committed
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-[#8B92A5]">
                        <span>{PROVIDER_LABELS[ws.provider]}</span>
                        <span aria-hidden="true">·</span>
                        <span className="font-mono text-[#CBD5E1]">{ws.branch}</span>
                        {ws.commitSha && (
                          <>
                            <span aria-hidden="true">·</span>
                            <span className="font-mono tabular-nums text-[#9CA3AF]">
                              {ws.commitSha}
                            </span>
                          </>
                        )}
                        <span aria-hidden="true">·</span>
                        <span className="font-mono tabular-nums text-[#22C55E]">+{additions}</span>
                        <span className="font-mono tabular-nums text-[#EF4444]">-{deletions}</span>
                      </div>

                      <div className="mt-3 flex flex-wrap items-center gap-2.5">
                        <button
                          type="button"
                          onClick={() => setInspectedId(ws.id)}
                          className="text-[12.5px] font-medium text-[#9CA3AF] hover:text-[#F3F4F6]"
                        >
                          Inspect {ws.files.length} file{ws.files.length === 1 ? '' : 's'}
                        </button>

                        {ws.gitState === 'uncommitted' && (
                          <button
                            type="button"
                            onClick={() => onCommitWorkstream(ws.id)}
                            aria-label={`Commit and stage ${ws.branch}`}
                            className="rounded-md border border-blue-500/40 bg-blue-500/10 px-2.5 py-1 text-[12px] font-medium text-blue-300 transition-colors hover:bg-blue-500/20 whitespace-nowrap"
                          >
                            Commit & Stage
                          </button>
                        )}

                        {ws.conflictState === 'conflict' && (
                          <button
                            type="button"
                            onClick={() => {
                              setInspectedId(ws.id);
                              onResolveConflict(ws.id, 'merged');
                            }}
                            aria-label={`Resolve merge conflict on ${ws.branch}`}
                            className="rounded-md border border-red-500/40 bg-red-500/10 px-2.5 py-1 text-[12px] font-medium text-red-300 transition-colors hover:bg-red-500/20 whitespace-nowrap"
                          >
                            Resolve Conflict (Merged)
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right: Diff & Conflict Inspector */}
        <aside className="rounded-xl border border-[#222630] bg-[#14171D] xl:col-span-5 flex flex-col">
          {inspected ? (
            <>
              <div className="border-b border-[#20242E] px-5 py-4">
                <p className="text-[12px] text-[#8B92A5]">
                  {PROVIDER_LABELS[inspected.provider]}
                  <span aria-hidden="true"> · </span>
                  <span className="font-mono">{inspected.upstreamStatus ?? inspected.branch}</span>
                </p>
                <h2 className="mt-1 text-[15px] font-semibold text-[#F9FAFB]">
                  {inspected.title}
                </h2>
                <p className="mt-1.5 text-[13px] leading-relaxed text-[#9CA3AF]">
                  {inspected.summary}
                </p>
              </div>

              {inspected.conflictState === 'conflict' && (
                <div className="border-b border-[#20242E] bg-[#1A1519] px-5 py-4">
                  <div className="flex items-start gap-2.5">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-[#EF4444]" aria-hidden="true" />
                    <div className="space-y-2.5 flex-1">
                      <p className="text-[13px] font-medium text-[#FCA5A5]">
                        Merge conflict requires resolution
                      </p>
                      <p className="text-[12.5px] text-[#D1D5DB]">
                        {inspected.conflictDetail}
                      </p>
                      <div className="flex flex-wrap items-center gap-2">
                        <label htmlFor="conflict-strategy" className="sr-only">
                          Conflict resolution strategy
                        </label>
                        <select
                          id="conflict-strategy"
                          value={strategyChoice}
                          onChange={(e) => setStrategyChoice(e.target.value as ResolutionStrategy)}
                          className="rounded-md border border-[#323846] bg-[#12151C] px-2.5 py-1.5 text-[12.5px] text-[#E5E7EB]"
                        >
                          <option value="merged">Merged (Keep Google + ChatGPT)</option>
                          <option value="ours">Keep Integration HEAD</option>
                          <option value="theirs">Accept Incoming Branch</option>
                        </select>
                        <button
                          type="button"
                          onClick={() => onResolveConflict(inspected.id, strategyChoice)}
                          className="rounded-md bg-blue-600 px-3 py-1.5 text-[12.5px] font-medium text-white hover:bg-blue-500"
                        >
                          Apply Resolution
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div className="divide-y divide-[#1E222C] flex-1">
                {inspected.files.map((file) => (
                  <div key={file.path} className="px-5 py-4 space-y-2.5">
                    <div className="flex items-center justify-between gap-2 text-[12.5px]">
                      <span className="flex items-center gap-2 min-w-0 font-mono text-[#E5E7EB]" title={file.path}>
                        <FileCode2 className="h-3.5 w-3.5 shrink-0 text-[#6B7280]" aria-hidden="true" />
                        <span className="truncate">{file.path}</span>
                      </span>
                      <span className="shrink-0 font-mono text-[11.5px] tabular-nums text-[#8B92A5]">
                        {file.status} · <span className="text-[#22C55E]">+{file.additions}</span>{' '}
                        <span className="text-[#EF4444]">-{file.deletions}</span>
                      </span>
                    </div>
                    <pre className="overflow-x-auto rounded-lg border border-[#222630] bg-[#0D0F13] p-3 font-mono text-[11.5px] leading-relaxed text-[#CBD5E1]">
                      <code>{file.preview}</code>
                    </pre>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="p-6 text-[13px] text-[#8B92A5]">
              Select a workstream to inspect changed files and diff hunks.
            </div>
          )}
        </aside>
      </div>

      {/* Register Workstream Modal */}
      {showAddModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs"
          role="dialog"
          aria-modal="true"
          aria-labelledby="add-ws-title"
        >
          <div className="w-full max-w-lg rounded-xl border border-[#292E3B] bg-[#14171D] shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#20242E] px-5 py-4">
              <h2 id="add-ws-title" className="text-[15px] font-semibold text-[#F9FAFB]">
                Register Workstream for Integration
              </h2>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                aria-label="Close modal"
                className="rounded-md p-1 text-[#9CA3AF] hover:bg-[#1E232F] hover:text-white"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>

            <form onSubmit={handleCreateWorkstream} className="space-y-4 p-5">
              {formError && (
                <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12.5px] text-red-300">
                  {formError}
                </p>
              )}

              <div>
                <label htmlFor="ws-title" className="block text-[12.5px] font-medium text-[#D1D5DB]">
                  Workstream Title
                </label>
                <input
                  id="ws-title"
                  type="text"
                  value={formTitle}
                  onChange={(e) => setFormTitle(e.target.value)}
                  placeholder="e.g. Google Chat slash command dispatcher"
                  className="mt-1.5 w-full rounded-lg border border-[#272C38] bg-[#0D0F13] px-3 py-2 text-[13px] text-[#F3F4F6] focus:border-blue-500 focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="ws-branch" className="block text-[12.5px] font-medium text-[#D1D5DB]">
                    Git Branch
                  </label>
                  <input
                    id="ws-branch"
                    type="text"
                    value={formBranch}
                    onChange={(e) => setFormBranch(e.target.value)}
                    placeholder="feat/google-chat-slash"
                    className="mt-1.5 w-full rounded-lg border border-[#272C38] bg-[#0D0F13] px-3 py-2 font-mono text-[12.5px] text-[#F3F4F6] focus:border-blue-500 focus:outline-none"
                  />
                </div>

                <div>
                  <label htmlFor="ws-provider" className="block text-[12.5px] font-medium text-[#D1D5DB]">
                    Provider Source
                  </label>
                  <select
                    id="ws-provider"
                    value={formProvider}
                    onChange={(e) => setFormProvider(e.target.value as ProviderSource)}
                    className="mt-1.5 w-full rounded-lg border border-[#272C38] bg-[#0D0F13] px-3 py-2 text-[13px] text-[#F3F4F6] focus:border-blue-500 focus:outline-none"
                  >
                    <option value="google">Google Chat / Gemini</option>
                    <option value="chatgpt">ChatGPT / OpenAI</option>
                    <option value="local">Local Git / Ollama</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="ws-git-state" className="block text-[12.5px] font-medium text-[#D1D5DB]">
                    Working Tree State
                  </label>
                  <select
                    id="ws-git-state"
                    value={formGitState}
                    onChange={(e) => setFormGitState(e.target.value as 'committed' | 'uncommitted')}
                    className="mt-1.5 w-full rounded-lg border border-[#272C38] bg-[#0D0F13] px-3 py-2 text-[13px] text-[#F3F4F6] focus:border-blue-500 focus:outline-none"
                  >
                    <option value="uncommitted">Uncommitted / Untracked</option>
                    <option value="committed">Committed</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="ws-filepath" className="block text-[12.5px] font-medium text-[#D1D5DB]">
                    Primary File Path
                  </label>
                  <input
                    id="ws-filepath"
                    type="text"
                    value={formFilePath}
                    onChange={(e) => setFormFilePath(e.target.value)}
                    placeholder="atlas-rust-desktop/src-tauri/resources/atlas/..."
                    className="mt-1.5 w-full rounded-lg border border-[#272C38] bg-[#0D0F13] px-3 py-2 font-mono text-[12.5px] text-[#F3F4F6] focus:border-blue-500 focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="ws-summary" className="block text-[12.5px] font-medium text-[#D1D5DB]">
                  Change Summary
                </label>
                <textarea
                  id="ws-summary"
                  rows={2}
                  value={formSummary}
                  onChange={(e) => setFormSummary(e.target.value)}
                  placeholder="Describe what this branch integrates into atlas-chat..."
                  className="mt-1.5 w-full rounded-lg border border-[#272C38] bg-[#0D0F13] px-3 py-2 text-[13px] text-[#F3F4F6] focus:border-blue-500 focus:outline-none"
                />
              </div>

              <div className="flex justify-end gap-2.5 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="rounded-lg border border-[#2C3240] px-4 py-2 text-[13px] font-medium text-[#D1D5DB] hover:bg-[#1C202A]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-medium text-white hover:bg-blue-500"
                >
                  Add Workstream
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
