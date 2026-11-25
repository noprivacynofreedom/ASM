import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Clock,
  FileCode2,
  GitBranch,
  Rocket,
} from 'lucide-react';
import { ActiveView, OrchestratorState, ProviderSource } from '../types/orchestrator';
import { ReadinessSummary } from '../utils/orchestrator';
import { ActionHistoryCard } from './ActionHistoryCard';

interface OverviewViewProps {
  state: OrchestratorState;
  readiness: ReadinessSummary;
  onNavigate: (view: ActiveView) => void;
  onCommitAllUncommitted: () => void;
  onVerifyAllIntegrated: () => void;
  onBuildBundle: () => void;
}

const PROVIDER_META: Array<{ id: ProviderSource; name: string; scope: string }> = [
  {
    id: 'google',
    name: 'Google Chat & Gemini / Vertex',
    scope: 'Dynamic Cloud Keys, streaming router & context compaction',
  },
  {
    id: 'chatgpt',
    name: 'ChatGPT / OpenAI',
    scope: 'Provider registry bridge, tool schemas & thread branching',
  },
  {
    id: 'local',
    name: 'Local Rust / Tauri & Ollama',
    scope: 'compare_mode.py, optional_modules.py, hexstrike-ai & swarm bus',
  },
];

export function OverviewView({
  state,
  readiness,
  onNavigate,
  onCommitAllUncommitted,
  onVerifyAllIntegrated,
  onBuildBundle,
}: OverviewViewProps) {
  const recentReplies = [...state.messages]
    .filter((m) => m.actionHistory)
    .slice(-2)
    .reverse();

  const missingOrPendingFeatures = state.features.filter((f) => f.status !== 'verified');

  return (
    <div className="mx-auto max-w-[1280px] space-y-8">
      {/* Header summary */}
      <div className="flex flex-col justify-between gap-4 border-b border-[#20242E] pb-6 md:flex-row md:items-end">
        <div className="max-w-2xl">
          <h1 className="text-[24px] font-semibold tracking-tight text-[#F9FAFB]">
            Conduit Agent Orchestration
          </h1>
          <p className="mt-1.5 text-[14px] text-[#9CA3AF]">
            Consolidating Google Chat/Gemini, ChatGPT, and local uncommitted workstreams for{' '}
            <span className="font-mono text-[#D1D5DB]">{state.projectName}</span> on{' '}
            <span className="font-mono text-[#D1D5DB]">{state.repoBranch}</span>.
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2.5 md:flex-nowrap">
          {readiness.uncommittedCount > 0 && (
            <button
              type="button"
              onClick={onCommitAllUncommitted}
              className="rounded-lg border border-[#2C3240] bg-[#171B24] px-3.5 py-2 text-[13px] font-medium text-[#E5E7EB] transition-colors hover:border-[#3B4254] hover:bg-[#1E232F] whitespace-nowrap shrink-0"
            >
              Commit {readiness.uncommittedCount} Uncommitted
            </button>
          )}
          {readiness.featuresIntegrated > 0 && (
            <button
              type="button"
              onClick={onVerifyAllIntegrated}
              className="rounded-lg border border-[#2C3240] bg-[#171B24] px-3.5 py-2 text-[13px] font-medium text-[#E5E7EB] transition-colors hover:border-[#3B4254] hover:bg-[#1E232F] whitespace-nowrap shrink-0"
            >
              Confirm {readiness.featuresIntegrated} Integrated
            </button>
          )}
          {readiness.canConsolidate && !state.bundle.isReady && (
            <button
              type="button"
              onClick={onBuildBundle}
              className="rounded-lg bg-blue-600 px-3.5 py-2 text-[13px] font-medium text-white transition-colors hover:bg-blue-500 whitespace-nowrap shrink-0"
            >
              Build Integration Bundle
            </button>
          )}
        </div>
      </div>

      {/* 4-column flat KPI strip */}
      <section aria-label="Release readiness metrics" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-[#222630] bg-[#14171D] p-5">
          <p className="text-[12.5px] font-medium text-[#9CA3AF]">Committed Workstreams</p>
          <p className="mt-2 font-mono text-[26px] font-semibold tabular-nums text-[#F9FAFB]">
            {readiness.committedCount}
            <span className="text-[15px] font-normal text-[#6B7280]"> / {readiness.selectedCount}</span>
          </p>
          <p className="mt-1.5 text-[12px] text-[#8B92A5]">
            {readiness.uncommittedCount === 0
              ? 'Working tree clean for bundle'
              : `${readiness.uncommittedCount} uncommitted pending commit`}
          </p>
        </div>

        <div className="rounded-xl border border-[#222630] bg-[#14171D] p-5">
          <p className="text-[12.5px] font-medium text-[#9CA3AF]">Merge Conflicts</p>
          <p
            className={`mt-2 font-mono text-[26px] font-semibold tabular-nums ${
              readiness.conflictCount > 0 ? 'text-[#EF4444]' : 'text-[#22C55E]'
            }`}
          >
            {readiness.conflictCount}
          </p>
          <p className="mt-1.5 text-[12px] text-[#8B92A5]">
            {readiness.conflictCount > 0
              ? 'Action required in src/providers/registry.ts'
              : 'All provider registries merged cleanly'}
          </p>
        </div>

        <div className="rounded-xl border border-[#222630] bg-[#14171D] p-5">
          <p className="text-[12.5px] font-medium text-[#9CA3AF]">Features Confirmed Working</p>
          <p className="mt-2 font-mono text-[26px] font-semibold tabular-nums text-[#F9FAFB]">
            {readiness.featuresVerified}
            <span className="text-[15px] font-normal text-[#6B7280]"> / {readiness.featuresTotal}</span>
          </p>
          <p className="mt-1.5 text-[12px] text-[#8B92A5]">
            {readiness.featuresMissing > 0
              ? `${readiness.featuresMissing} missing · ${readiness.featuresIntegrated} awaiting test`
              : readiness.featuresIntegrated > 0
                ? `${readiness.featuresIntegrated} integrated awaiting check`
                : 'All atlas-chat features verified'}
          </p>
        </div>

        <div className="rounded-xl border border-[#222630] bg-[#14171D] p-5">
          <p className="text-[12.5px] font-medium text-[#9CA3AF]">Production Rollout</p>
          <p className="mt-2 font-mono text-[26px] font-semibold tabular-nums text-[#F9FAFB]">
            {state.pipeline.canaryPercent}%
          </p>
          <p className="mt-1.5 text-[12px] text-[#8B92A5]">
            {state.pipeline.status === 'live'
              ? 'Live in production (v2.4.0)'
              : state.pipeline.status === 'awaiting_approval'
                ? 'Paused at Canary approval gate'
                : state.pipeline.status === 'rolled_back'
                  ? 'Rolled back to atlas-chat@v2.3.9'
                  : readiness.canDeployToProd
                    ? 'Ready to launch rollout'
                    : `${readiness.blockers.length} gate blocker${readiness.blockers.length === 1 ? '' : 's'}`}
          </p>
        </div>
      </section>

      {/* Main 2-column grid */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        {/* Left: Provider Consolidation Matrix + Missing Features Gate */}
        <div className="space-y-6 xl:col-span-7">
          <section className="rounded-xl border border-[#222630] bg-[#14171D]">
            <div className="flex items-center justify-between border-b border-[#20242E] px-5 py-4">
              <div>
                <h2 className="text-[15px] font-semibold text-[#F9FAFB]">
                  Provider Consolidation Status
                </h2>
                <p className="mt-0.5 text-[12.5px] text-[#8B92A5]">
                  Committed and uncommitted streams across Google, ChatGPT, and Local environments
                </p>
              </div>
              <button
                type="button"
                onClick={() => onNavigate('workstreams')}
                className="flex items-center gap-1.5 text-[12.5px] font-medium text-blue-400 hover:text-blue-300 whitespace-nowrap"
              >
                <span>Manage streams</span>
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-[13px]">
                <thead>
                  <tr className="border-b border-[#20242E] text-[12px] text-[#6B7280]">
                    <th className="px-5 py-3 font-medium">Provider</th>
                    <th className="px-4 py-3 font-medium text-right whitespace-nowrap">Committed</th>
                    <th className="px-4 py-3 font-medium text-right whitespace-nowrap">Uncommitted</th>
                    <th className="px-5 py-3 font-medium text-right whitespace-nowrap">State</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1D212B]">
                  {PROVIDER_META.map((prov) => {
                    const list = state.workstreams.filter((w) => w.provider === prov.id);
                    const committed = list.filter((w) => w.gitState === 'committed').length;
                    const uncommitted = list.filter((w) => w.gitState === 'uncommitted').length;
                    const conflicts = list.filter((w) => w.conflictState === 'conflict').length;

                    return (
                      <tr key={prov.id} className="hover:bg-[#181C24] transition-colors">
                        <td className="px-5 py-3.5">
                          <p className="font-medium text-[#E5E7EB]">{prov.name}</p>
                          <p className="mt-0.5 text-[12px] text-[#8B92A5]">{prov.scope}</p>
                        </td>
                        <td className="px-4 py-3.5 text-right font-mono tabular-nums text-[#D1D5DB]">
                          {committed}
                        </td>
                        <td className="px-4 py-3.5 text-right font-mono tabular-nums text-[#D1D5DB]">
                          {uncommitted}
                        </td>
                        <td className="px-5 py-3.5 text-right whitespace-nowrap">
                          {conflicts > 0 ? (
                            <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-[#EF4444] whitespace-nowrap">
                              <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                              Conflict
                            </span>
                          ) : uncommitted > 0 ? (
                            <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-[#F59E0B] whitespace-nowrap">
                              <Clock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                              Pending Commit
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-[#22C55E] whitespace-nowrap">
                              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                              Ready
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {/* Missing & Pending Features tracker */}
          <section className="rounded-xl border border-[#222630] bg-[#14171D]">
            <div className="flex items-center justify-between border-b border-[#20242E] px-5 py-4">
              <div>
                <h2 className="text-[15px] font-semibold text-[#F9FAFB]">
                  Missing & Unverified Features Gate
                </h2>
                <p className="mt-0.5 text-[12.5px] text-[#8B92A5]">
                  Every feature must be integrated and confirmed working before production cutover
                </p>
              </div>
              <button
                type="button"
                onClick={() => onNavigate('pipeline')}
                className="flex items-center gap-1.5 text-[12.5px] font-medium text-blue-400 hover:text-blue-300 whitespace-nowrap"
              >
                <span>Open pipeline</span>
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>

            {missingOrPendingFeatures.length === 0 ? (
              <div className="flex items-center justify-between gap-4 px-5 py-6">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="h-5 w-5 text-[#22C55E]" aria-hidden="true" />
                  <div>
                    <p className="text-[14px] font-medium text-[#F9FAFB]">
                      All {state.features.length} atlas-chat features are integrated and confirmed working
                    </p>
                    <p className="text-[12.5px] text-[#8B92A5]">
                      Unit, Integration, and E2E gates are satisfied for staged production rollout.
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onNavigate('pipeline')}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-[13px] font-medium text-white hover:bg-blue-500 whitespace-nowrap"
                >
                  <Rocket className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>Deploy</span>
                </button>
              </div>
            ) : (
              <ul className="divide-y divide-[#1D212B]">
                {missingOrPendingFeatures.slice(0, 6).map((feat) => (
                  <li key={feat.id} className="flex items-center justify-between gap-4 px-5 py-3">
                    <div className="min-w-0">
                      <p className="truncate text-[13.5px] font-medium text-[#E5E7EB]">
                        {feat.name}
                      </p>
                      <p className="mt-0.5 truncate text-[12px] text-[#8B92A5]">
                        <span>{feat.category}</span>
                        <span aria-hidden="true"> · </span>
                        <span className="font-mono">{feat.suite}</span>
                        <span aria-hidden="true"> · </span>
                        <span>{feat.notes}</span>
                      </p>
                    </div>
                    <span
                      className={`shrink-0 inline-flex items-center gap-1.5 text-[12px] font-medium ${
                        feat.status === 'missing' ? 'text-[#F59E0B]' : 'text-blue-400'
                      }`}
                    >
                      {feat.status === 'missing' ? (
                        <>
                          <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                          Missing
                        </>
                      ) : (
                        <>
                          <FileCode2 className="h-3.5 w-3.5" aria-hidden="true" />
                          Integrated
                        </>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* Right: Recent Swarm Replies with Google-style Action History Cards */}
        <section className="rounded-xl border border-[#222630] bg-[#14171D] xl:col-span-5 flex flex-col">
          <div className="flex items-center justify-between border-b border-[#20242E] px-5 py-4">
            <div>
              <h2 className="text-[15px] font-semibold text-[#F9FAFB]">
                Latest Swarm Replies & Action History
              </h2>
              <p className="mt-0.5 text-[12.5px] text-[#8B92A5]">
                Structured model replies synced with DEVLOG.md
              </p>
            </div>
            <button
              type="button"
              onClick={() => onNavigate('swarm')}
              className="flex items-center gap-1.5 text-[12.5px] font-medium text-blue-400 hover:text-blue-300 whitespace-nowrap"
            >
              <span>Swarm board</span>
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>

          <div className="divide-y divide-[#1D212B] flex-1">
            {recentReplies.map((msg) => {
              const sender = state.agents.find((a) => a.id === msg.senderAgentId);
              return (
                <article key={msg.id} className="p-5">
                  <div className="flex items-center justify-between gap-2 text-[12.5px]">
                    <div className="flex items-center gap-2 text-[#9CA3AF]">
                      <span className="font-semibold text-[#F3F4F6]">
                        {sender?.displayName ?? 'Agent'}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span className="font-mono text-[11.5px] text-[#8B92A5]">
                        #{msg.channelId}
                      </span>
                    </div>
                    <span className="font-mono text-[11.5px] tabular-nums text-[#6B7280]">
                      {msg.createdAt.slice(11, 16)} UTC
                    </span>
                  </div>

                  <p className="mt-2 text-[13.5px] leading-relaxed text-[#D1D5DB]">
                    {msg.body}
                  </p>

                  {msg.actionHistory && (
                    <ActionHistoryCard block={msg.actionHistory} defaultExpanded={true} />
                  )}
                </article>
              );
            })}
          </div>

          <div className="border-t border-[#20242E] px-5 py-3.5 flex items-center justify-between text-[12.5px] text-[#8B92A5]">
            <span className="flex items-center gap-2">
              <GitBranch className="h-3.5 w-3.5 text-[#6B7280]" aria-hidden="true" />
              <span>Bundle: <span className="font-mono text-[#D1D5DB]">{state.bundle.version}</span></span>
            </span>
            <button
              type="button"
              onClick={() => onNavigate('swarm')}
              className="font-medium text-[#E5E7EB] hover:text-blue-400 transition-colors"
            >
              Open DEVLOG.md Sync
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
