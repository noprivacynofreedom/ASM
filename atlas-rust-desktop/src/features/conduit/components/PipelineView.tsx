import { useMemo, useState } from 'react';
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  FlaskConical,
  Play,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { OrchestratorState, RolloutMode } from '../types/orchestrator';
import { filterRunLogs, ReadinessSummary } from '../utils/orchestrator';

interface PipelineViewProps {
  state: OrchestratorState;
  readiness: ReadinessSummary;
  onSetRolloutMode: (mode: RolloutMode) => void;
  onVerifyFeature: (featureId: string) => void;
  onVerifyAllIntegrated: () => void;
  onStartRollout: () => void;
  onPromoteToProduction: () => void;
  onRollback: () => void;
  onRunGeminiAudit: () => Promise<void>;
  auditLoading: boolean;
  auditError: string | null;
}

export function PipelineView({
  state,
  readiness,
  onSetRolloutMode,
  onVerifyFeature,
  onVerifyAllIntegrated,
  onStartRollout,
  onPromoteToProduction,
  onRollback,
  onRunGeminiAudit,
  auditLoading,
  auditError,
}: PipelineViewProps) {
  const [logFilter, setLogFilter] = useState<'all' | 'hide_routine' | 'problems'>('all');
  const [expandedLogIds, setExpandedLogIds] = useState<Record<string, boolean>>({});
  const [copiedLog, setCopiedLog] = useState(false);

  const visibleLogs = useMemo(
    () => filterRunLogs(state.pipeline.runLog, logFilter),
    [state.pipeline.runLog, logFilter]
  );

  const problemCount = state.pipeline.runLog.filter((l) => l.severity === 'problem').length;

  const toggleLogDetail = (id: string) => {
    setExpandedLogIds((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleCopyLog = () => {
    const text = visibleLogs
      .map((l) => `${l.timestamp} [${l.agentLabel}] ${l.message}${l.detail ? ` — ${l.detail}` : ''}`)
      .join('\n');
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).catch(() => {});
    }
    setCopiedLog(true);
    setTimeout(() => setCopiedLog(false), 1800);
  };

  return (
    <div className="mx-auto max-w-[1280px] space-y-6">
      {/* Header & Rollout Mode Selector */}
      <div className="flex flex-col justify-between gap-4 border-b border-[#20242E] pb-5 lg:flex-row lg:items-end">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-[#F9FAFB]">
            Production Rollout Pipeline
          </h1>
          <p className="mt-1 text-[13.5px] text-[#9CA3AF]">
            Git-integrated build, automated Unit / Integration / E2E matrix, and staged rollout for{' '}
            <span className="font-mono text-[#D1D5DB]">{state.bundle.version}</span>.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {/* Fast HotSync vs Full Installer rollout mode */}
          <div
            className="inline-flex items-center rounded-lg border border-[#222630] bg-[#14171D] p-1"
            role="group"
            aria-label="Deployment strategy"
          >
            <button
              type="button"
              onClick={() => onSetRolloutMode('hotsync')}
              className={`rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors whitespace-nowrap ${
                state.pipeline.rolloutMode === 'hotsync'
                  ? 'bg-[#222836] text-[#F9FAFB]'
                  : 'text-[#8B92A5] hover:text-[#E5E7EB]'
              }`}
            >
              HotSync (sync-live.ps1)
            </button>
            <button
              type="button"
              onClick={() => onSetRolloutMode('full_installer')}
              className={`rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors whitespace-nowrap ${
                state.pipeline.rolloutMode === 'full_installer'
                  ? 'bg-[#222836] text-[#F9FAFB]'
                  : 'text-[#8B92A5] hover:text-[#E5E7EB]'
              }`}
            >
              Full Release (build-release.ps1)
            </button>
          </div>

          <button
            type="button"
            onClick={onRunGeminiAudit}
            disabled={auditLoading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[#2C3240] bg-[#171B24] px-3.5 py-2 text-[13px] font-medium text-[#E5E7EB] transition-colors hover:bg-[#1E232F] disabled:opacity-60 whitespace-nowrap"
          >
            <Sparkles className="h-3.5 w-3.5 text-blue-400" aria-hidden="true" />
            <span>{auditLoading ? 'Auditing...' : 'Gemini Preflight Audit'}</span>
          </button>

          {state.pipeline.status === 'awaiting_approval' ? (
            <>
              <button
                type="button"
                onClick={onRollback}
                className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/40 bg-red-500/10 px-3.5 py-2 text-[13px] font-medium text-red-300 hover:bg-red-500/20 whitespace-nowrap"
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Rollback</span>
              </button>
              <button
                type="button"
                onClick={onPromoteToProduction}
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-[13px] font-medium text-white hover:bg-emerald-500 whitespace-nowrap"
              >
                <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                <span>Approve & Promote to Production</span>
              </button>
            </>
          ) : state.pipeline.status === 'live' ? (
            <button
              type="button"
              onClick={onRollback}
              className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/40 bg-red-500/10 px-3.5 py-2 text-[13px] font-medium text-red-300 hover:bg-red-500/20 whitespace-nowrap"
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Rollback Release</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={onStartRollout}
              disabled={!readiness.canDeployToProd}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-[#232836] disabled:text-[#6B7280] whitespace-nowrap"
            >
              <Play className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Start Rollout</span>
            </button>
          )}
        </div>
      </div>

      {/* Preflight Audit Result or Error */}
      {auditError && (
        <div role="alert" className="rounded-xl border border-red-500/30 bg-[#1B1418] px-4 py-3 text-[13px] text-red-300">
          {auditError}
        </div>
      )}
      {state.pipeline.aiAuditReport && (
        <section className="rounded-xl border border-[#282E3D] bg-[#16181D] p-5">
          <div className="flex items-center justify-between gap-2 text-[12.5px] text-[#9CA3AF]">
            <span className="font-medium text-[#E5E7EB]">
              Gemini 4 Hydrogen · Preflight Rollout Audit
            </span>
            {state.pipeline.aiAuditGeneratedAt && (
              <span className="font-mono tabular-nums text-[11.5px]">
                {state.pipeline.aiAuditGeneratedAt.slice(11, 19)} UTC
              </span>
            )}
          </div>
          <p className="mt-2.5 whitespace-pre-wrap text-[13.5px] leading-relaxed text-[#D1D5DB]">
            {state.pipeline.aiAuditReport}
          </p>
        </section>
      )}

      {/* Rollout Blockers Callout if any */}
      {!readiness.canDeployToProd && (
        <div className="rounded-xl border border-amber-500/25 bg-[#191713] px-5 py-4">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
            <div>
              <p className="text-[13.5px] font-medium text-amber-300">
                Rollout gate locked ({readiness.blockers.length} requirement
                {readiness.blockers.length === 1 ? '' : 's'} remaining)
              </p>
              <ul className="mt-1.5 space-y-1 text-[12.5px] text-[#D1D5DB]">
                {readiness.blockers.map((b) => (
                  <li key={b}>· {b}</li>
                ))}
              </ul>
            </div>
            {readiness.featuresIntegrated > 0 && (
              <button
                type="button"
                onClick={onVerifyAllIntegrated}
                className="shrink-0 rounded-lg bg-blue-600 px-3.5 py-2 text-[13px] font-medium text-white hover:bg-blue-500 whitespace-nowrap"
              >
                Confirm All Integrated Features ({readiness.featuresIntegrated})
              </button>
            )}
          </div>
        </div>
      )}

      {/* 4-Stage Pipeline Progression */}
      <section aria-label="Deployment stages" className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {state.pipeline.stages.map((stage, idx) => (
          <div
            key={stage.id}
            className="flex flex-col justify-between rounded-xl border border-[#222630] bg-[#14171D] p-5"
          >
            <div>
              <div className="flex items-center justify-between gap-2 text-[12px]">
                <span className="font-mono text-[#8B92A5]">Stage {idx + 1} of 4</span>
                {stage.status === 'passed' && (
                  <span className="inline-flex items-center gap-1 font-medium text-[#22C55E]">
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                    Passed
                  </span>
                )}
                {stage.status === 'awaiting_approval' && (
                  <span className="inline-flex items-center gap-1 font-medium text-[#F59E0B]">
                    <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                    Canary Gate
                  </span>
                )}
                {stage.status === 'rolled_back' && (
                  <span className="inline-flex items-center gap-1 font-medium text-[#EF4444]">
                    <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
                    Rolled Back
                  </span>
                )}
                {stage.status === 'idle' && (
                  <span className="font-medium text-[#6B7280]">Standby</span>
                )}
              </div>

              <h2 className="mt-2.5 text-[14.5px] font-semibold text-[#F9FAFB]">{stage.name}</h2>
              <p className="mt-1 text-[12.5px] leading-relaxed text-[#8B92A5]">
                {stage.description}
              </p>
            </div>

            <div className="mt-4 border-t border-[#1E222C] pt-3">
              <div className="space-y-1 font-mono text-[11.5px] text-[#9CA3AF]">
                {stage.logs.slice(-2).map((line, i) => (
                  <p key={i} className="truncate" title={line}>
                    {line}
                  </p>
                ))}
              </div>
              {stage.durationSec !== null && (
                <p className="mt-2 font-mono text-[11px] tabular-nums text-[#6B7280]">
                  Duration: {stage.durationSec}s
                </p>
              )}
            </div>
          </div>
        ))}
      </section>

      {/* Automated Test Matrix (Unit, Integration, E2E) */}
      <section className="rounded-xl border border-[#222630] bg-[#14171D]">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#20242E] px-5 py-4">
          <div>
            <h2 className="text-[15px] font-semibold text-[#F9FAFB]">
              Automated Test Matrix (Unit · Integration · End-to-End)
            </h2>
            <p className="mt-0.5 text-[12.5px] text-[#8B92A5]">
              {state.pipeline.rolloutMode === 'hotsync'
                ? 'Active target: Fast HotSync (sync-live.ps1 -CloseApp -Launch · Python/UI resources)'
                : 'Active target: Full NSIS Release Build (build-release.ps1 · Nuitka + Vite + Rust/Tauri + SHA256 verification)'}
            </p>
          </div>
          {readiness.featuresIntegrated > 0 && (
            <button
              type="button"
              onClick={onVerifyAllIntegrated}
              className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-[12.5px] font-medium text-blue-300 hover:bg-blue-500/20 whitespace-nowrap"
            >
              <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Run Verification Matrix</span>
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 divide-y divide-[#1E222C] md:grid-cols-3 md:divide-x md:divide-y-0">
          {state.pipeline.testSuites.map((suite) => (
            <div key={suite.id} className="p-5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13.5px] font-semibold text-[#E5E7EB]">{suite.label}</span>
                {suite.status === 'passed' ? (
                  <span className="inline-flex items-center gap-1 text-[12px] font-medium text-[#22C55E]">
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                    Passed
                  </span>
                ) : suite.status === 'blocked' ? (
                  <span className="inline-flex items-center gap-1 text-[12px] font-medium text-[#F59E0B]">
                    <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                    Blocked
                  </span>
                ) : (
                  <span className="text-[12px] font-medium text-blue-400">Ready</span>
                )}
              </div>

              <p className="mt-2 font-mono text-[20px] font-semibold tabular-nums text-[#F9FAFB]">
                {suite.passed}
                <span className="text-[13px] font-normal text-[#6B7280]"> / {suite.total} assertions</span>
              </p>

              <p className="mt-2 truncate font-mono text-[11.5px] text-[#8B92A5]" title={suite.command}>
                {suite.command}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Feature Parity & Missing Feature Confirmation Table */}
      <section className="rounded-xl border border-[#222630] bg-[#14171D]">
        <div className="flex items-center justify-between border-b border-[#20242E] px-5 py-4">
          <div>
            <h2 className="text-[15px] font-semibold text-[#F9FAFB]">
              Atlas Chat Feature Parity & Confirmation Checklist
            </h2>
            <p className="mt-0.5 text-[12.5px] text-[#8B92A5]">
              Confirm every previously missing feature is integrated and verified working before production cutover
            </p>
          </div>
          <span className="font-mono text-[12.5px] tabular-nums text-[#9CA3AF]">
            {readiness.featuresVerified}/{readiness.featuresTotal} confirmed
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="border-b border-[#20242E] text-[12px] text-[#6B7280]">
                <th className="px-5 py-3 font-medium">Feature</th>
                <th className="px-4 py-3 font-medium">Suite</th>
                <th className="px-4 py-3 font-medium text-right">Assertions</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-5 py-3 font-medium text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1D212B]">
              {state.features.map((feat) => (
                <tr key={feat.id} className="hover:bg-[#181C24] transition-colors">
                  <td className="px-5 py-3.5">
                    <p className="font-medium text-[#E5E7EB]">{feat.name}</p>
                    <p className="mt-0.5 text-[12px] text-[#8B92A5]">{feat.notes}</p>
                  </td>
                  <td className="px-4 py-3.5 font-mono text-[12px] text-[#9CA3AF]">
                    {feat.suite}
                  </td>
                  <td className="px-4 py-3.5 text-right font-mono tabular-nums text-[#D1D5DB]">
                    {feat.assertionsPassed}/{feat.assertionsTotal}
                  </td>
                  <td className="px-4 py-3.5">
                    {feat.status === 'verified' ? (
                      <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-[#22C55E]">
                        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                        Confirmed Working
                      </span>
                    ) : feat.status === 'integrated' ? (
                      <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-blue-400">
                        <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                        Integrated
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-[#F59E0B]">
                        <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
                        Missing
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    {feat.status === 'integrated' ? (
                      <button
                        type="button"
                        onClick={() => onVerifyFeature(feat.id)}
                        className="rounded-md border border-blue-500/40 bg-blue-500/10 px-2.5 py-1 text-[12px] font-medium text-blue-300 hover:bg-blue-500/20 whitespace-nowrap"
                      >
                        Confirm Working
                      </button>
                    ) : feat.status === 'verified' ? (
                      <span className="font-mono text-[11.5px] text-[#6B7280]">Verified</span>
                    ) : (
                      <span className="text-[12px] text-[#6B7280]">Commit stream first</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Structured Run Log (inspired by Atlas Chat Run Log, ultra-clean obsidian styling) */}
      <section className="rounded-xl border border-[#222630] bg-[#14171D]">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#20242E] px-5 py-3.5">
          <div className="flex items-center gap-2 text-[13px]">
            <h2 className="font-semibold text-[#F9FAFB]">Run Log</h2>
            <span className="text-[#6B7280]" aria-hidden="true">·</span>
            <span className="font-mono text-[12px] tabular-nums text-[#8B92A5]">
              {state.pipeline.runLog.length} lines
            </span>
            <span className="text-[#6B7280]" aria-hidden="true">·</span>
            <span
              className={`font-mono text-[12px] tabular-nums ${
                problemCount > 0 ? 'text-[#EF4444]' : 'text-[#22C55E]'
              }`}
            >
              {problemCount} problem{problemCount === 1 ? '' : 's'}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <div className="inline-flex items-center rounded-lg border border-[#252A36] bg-[#0F1218] p-0.5" role="group" aria-label="Filter run log">
              {(
                [
                  { id: 'all', label: 'All' },
                  { id: 'hide_routine', label: 'Hide Routine' },
                  { id: 'problems', label: 'Problems' },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setLogFilter(tab.id)}
                  className={`rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors whitespace-nowrap ${
                    logFilter === tab.id
                      ? 'bg-[#222836] text-[#F9FAFB]'
                      : 'text-[#8B92A5] hover:text-[#E5E7EB]'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={handleCopyLog}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[#282D3A] bg-[#171B24] px-3 py-1.5 text-[12px] font-medium text-[#D1D5DB] hover:bg-[#1E232F] whitespace-nowrap"
            >
              {copiedLog ? (
                <>
                  <Check className="h-3.5 w-3.5 text-[#22C55E]" aria-hidden="true" />
                  <span>Copied</span>
                </>
              ) : (
                <>
                  <Copy className="h-3.5 w-3.5 text-[#9CA3AF]" aria-hidden="true" />
                  <span>Copy Log</span>
                </>
              )}
            </button>
          </div>
        </div>

        <div className="divide-y divide-[#1C202A]">
          {visibleLogs.length === 0 ? (
            <p className="px-5 py-6 text-[13px] text-[#8B92A5]">
              No log entries match the selected filter.
            </p>
          ) : (
            visibleLogs.map((entry) => {
              const isExpanded = Boolean(expandedLogIds[entry.id]);
              return (
                <div key={entry.id} className="px-5 py-3 text-[13px]">
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 shrink-0 font-mono text-[11.5px] tabular-nums text-[#6B7280]">
                      {entry.timestamp}
                    </span>

                    {entry.detail ? (
                      <button
                        type="button"
                        onClick={() => toggleLogDetail(entry.id)}
                        aria-expanded={isExpanded}
                        aria-label={`Toggle details for ${entry.message}`}
                        className="mt-0.5 shrink-0 text-[#6B7280] hover:text-[#E5E7EB]"
                      >
                        {isExpanded ? (
                          <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
                        )}
                      </button>
                    ) : (
                      <span className="w-3.5 shrink-0" />
                    )}

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <span
                          className={`font-mono text-[11.5px] font-medium ${
                            entry.severity === 'problem'
                              ? 'text-[#EF4444]'
                              : entry.severity === 'milestone'
                                ? 'text-blue-400'
                                : 'text-[#8B92A5]'
                          }`}
                        >
                          {entry.agentLabel}
                        </span>
                        <span className="text-[#E5E7EB]">{entry.message}</span>
                      </div>

                      {isExpanded && entry.detail && (
                        <p className="mt-1.5 rounded-lg border border-[#222630] bg-[#0E1117] px-3 py-2 font-mono text-[12px] text-[#9CA3AF]">
                          {entry.detail}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}
