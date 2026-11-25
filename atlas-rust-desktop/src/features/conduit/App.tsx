import { useCallback, useEffect, useMemo, useState } from 'react';
import { createInitialState } from './data/seedData';
import {
  ActiveView,
  MessageKind,
  OrchestratorState,
  ProviderSource,
  ResolutionStrategy,
  RolloutMode,
  SwarmChannelId,
} from './types/orchestrator';
import {
  acknowledgeSwarmMessage,
  addWorkstream,
  buildIntegrationBundle,
  commitAllUncommitted,
  commitWorkstream,
  computeReadiness,
  executeSwarmSlashCommand,
  postSwarmMessage,
  promoteToProduction,
  resolveConflict,
  rollbackProduction,
  setRolloutMode,
  startRolloutPipeline,
  toggleWorkstreamSelection,
  verifyAllIntegratedFeatures,
  verifyFeature,
} from './utils/orchestrator';
import { Sidebar } from './components/Sidebar';
import { TopBar } from './components/TopBar';
import { OverviewView } from './components/OverviewView';
import { WorkstreamsView } from './components/WorkstreamsView';
import { PipelineView } from './components/PipelineView';
import { SwarmBoardView } from './components/SwarmBoardView';
import { CtfWorkbenchView } from './components/CtfWorkbenchView';

const STORAGE_KEY = 'conduit.atlas_chat.state.v1';

export default function App() {
  const [state, setState] = useState<OrchestratorState>(() => {
    try {
      const cached = localStorage.getItem(STORAGE_KEY);
      if (cached) {
        const parsed = JSON.parse(cached) as OrchestratorState;
        if (parsed?.workstreams && parsed?.pipeline && parsed?.messages) {
          return parsed;
        }
      }
    } catch {
      // ignore invalid cache
    }
    return createInitialState();
  });

  const [activeView, setActiveView] = useState<ActiveView>('overview');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [devlogMarkdown, setDevlogMarkdown] = useState<string>('');
  const [statusNotice, setStatusNotice] = useState<string | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [geminiReplyLoading, setGeminiReplyLoading] = useState(false);
  const [geminiReplyError, setGeminiReplyError] = useState<string | null>(null);

  const readiness = useMemo(
    () => computeReadiness(state.workstreams, state.features),
    [state.workstreams, state.features]
  );

  const flashNotice = useCallback((msg: string) => {
    setStatusNotice(msg);
  }, []);

  useEffect(() => {
    if (!statusNotice) return;
    const t = setTimeout(() => setStatusNotice(null), 4000);
    return () => clearTimeout(t);
  }, [statusNotice]);

  // Hydrate persisted state & DEVLOG.md from Atlas local backend on initial load
  const CONDUIT_API_BASE = 'http://127.0.0.1:8090/api/conduit';
  useEffect(() => {
    let active = true;
    fetch(`${CONDUIT_API_BASE}/state`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && data?.state?.workstreams && data?.state?.pipeline) {
          setState(data.state as OrchestratorState);
        }
      })
      .catch(() => {});

    fetch(`${CONDUIT_API_BASE}/devlog`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && typeof data?.content === 'string') {
          setDevlogMarkdown(data.content);
        }
      })
      .catch(() => {});

    return () => {
      active = false;
    };
  }, []);

  const persistState = useCallback((next: OrchestratorState) => {
    setState(next);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // ignore storage quota errors
    }
    fetch(`${CONDUIT_API_BASE}/state`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state: next }),
    }).catch(() => {});
  }, []);

  const appendDevlog = useCallback(
    async (entry: {
      title: string;
      authorHandle: string;
      targetHandle: string;
      branch?: string;
      summary: string;
      files?: string[];
    }) => {
      try {
        const res = await fetch(`${CONDUIT_API_BASE}/devlog`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(entry),
        });
        if (res.ok) {
          const data = await res.json();
          if (typeof data?.content === 'string') {
            setDevlogMarkdown(data.content);
          }
        }
      } catch {
        // non-blocking devlog sync
      }
    },
    []
  );

  const handleCommitWorkstream = (id: string) => {
    const ws = state.workstreams.find((w) => w.id === id);
    const next = commitWorkstream(state, id);
    persistState(next);
    if (ws) {
      flashNotice(`Committed & staged ${ws.branch}. Linked features moved to Integrated.`);
      void appendDevlog({
        title: `Committed ${ws.branch}`,
        authorHandle: '@local-sde-runner',
        targetHandle: '@all-agents',
        branch: ws.branch,
        summary: `Staged ${ws.files.length} files for atlas-chat integration bundle.`,
        files: ws.files.map((f) => f.path),
      });
    }
  };

  const handleCommitAllUncommitted = () => {
    const count = state.workstreams.filter((w) => w.gitState === 'uncommitted').length;
    const next = commitAllUncommitted(state);
    persistState(next);
    flashNotice(`Committed & staged ${count} uncommitted workstreams.`);
    void appendDevlog({
      title: `Batch Commit (${count} Workstreams)`,
      authorHandle: '@release-lead',
      targetHandle: '@all-agents',
      branch: state.repoBranch,
      summary: `Committed all ${count} pending Google, ChatGPT, and Local patches into clean git history.`,
    });
  };

  const handleResolveConflict = (id: string, strategy: ResolutionStrategy) => {
    const ws = state.workstreams.find((w) => w.id === id);
    const next = resolveConflict(state, id, strategy);
    persistState(next);
    if (ws) {
      flashNotice(`Resolved conflict on ${ws.branch} using "${strategy}" strategy.`);
      void appendDevlog({
        title: `Resolved Merge Conflict (${ws.branch})`,
        authorHandle: '@release-lead',
        targetHandle: '@all-agents',
        branch: ws.branch,
        summary: `Applied "${strategy}" resolution on src/providers/registry.ts so Google and ChatGPT adapters coexist cleanly.`,
      });
    }
  };

  const handleToggleSelection = (id: string) => {
    persistState(toggleWorkstreamSelection(state, id));
  };

  const handleAddWorkstream = (input: {
    title: string;
    branch: string;
    provider: ProviderSource;
    gitState: 'committed' | 'uncommitted';
    summary: string;
    filePath: string;
  }) => {
    const next = addWorkstream(state, input);
    persistState(next);
    flashNotice(`Registered workstream ${input.branch}.`);
  };

  const handleVerifyFeature = (featureId: string) => {
    const feat = state.features.find((f) => f.id === featureId);
    const next = verifyFeature(state, featureId);
    persistState(next);
    if (feat) {
      flashNotice(`Confirmed "${feat.name}" working (${feat.assertionsTotal}/${feat.assertionsTotal}).`);
    }
  };

  const handleVerifyAllIntegrated = () => {
    const count = state.features.filter((f) => f.status === 'integrated').length;
    const next = verifyAllIntegratedFeatures(state);
    persistState(next);
    flashNotice(`Confirmed ${count} integrated atlas-chat features working across test suites.`);
    void appendDevlog({
      title: `Verified ${count} Integrated Features`,
      authorHandle: '@local-sde-runner',
      targetHandle: '@release-lead',
      branch: state.bundle.targetBranch,
      summary: `Confirmed ${count} newly integrated atlas-chat features passed Unit, Integration, and E2E verification.`,
    });
  };

  const handleBuildBundle = () => {
    const result = buildIntegrationBundle(state);
    if (!result.ok) {
      flashNotice(result.error ?? 'Resolve blockers before building integration bundle.');
      return;
    }
    persistState(result.state);
    flashNotice(`Built unified integration bundle ${result.state.bundle.version}.`);
    void appendDevlog({
      title: `Consolidated ${result.state.bundle.version}`,
      authorHandle: '@release-lead',
      targetHandle: '@all-agents',
      branch: result.state.bundle.targetBranch,
      summary: `Merged ${result.state.bundle.workstreamIds.length} workstreams (${result.state.bundle.totalFiles} files) into release candidate.`,
    });
  };

  const handleSetRolloutMode = (mode: RolloutMode) => {
    persistState(setRolloutMode(state, mode));
  };

  const handleStartRollout = () => {
    const result = startRolloutPipeline(state);
    if (!result.ok) {
      flashNotice(result.error ?? 'Complete all gates before starting rollout.');
      return;
    }
    persistState(result.state);
    setActiveView('pipeline');
    flashNotice('Staged Canary Rollout reached 50% healthy traffic. Awaiting Release Lead sign-off.');
    void appendDevlog({
      title: `Staged Canary Rollout (${result.state.pipeline.rolloutMode})`,
      authorHandle: '@gemini-architect',
      targetHandle: '@release-lead',
      branch: result.state.bundle.targetBranch,
      summary: 'Unit, Integration, and E2E suites passed. Canary traffic at 50% awaiting 100% production sign-off.',
    });
  };

  const handlePromoteToProduction = () => {
    const next = promoteToProduction(state);
    persistState(next);
    flashNotice('atlas-chat@v2.4.0-prod promoted to 100% production traffic.');
    void appendDevlog({
      title: 'Production Cutover Complete (100%)',
      authorHandle: '@release-lead',
      targetHandle: '@all-agents',
      branch: state.bundle.targetBranch,
      summary: 'Promoted atlas-chat@v2.4.0-prod globally with rollback snapshot armed at atlas-chat@v2.3.9.',
    });
  };

  const handleRollback = () => {
    const next = rollbackProduction(state, 'Release Lead triggered instant rollback');
    persistState(next);
    flashNotice('Rolled back production traffic safely to atlas-chat@v2.3.9.');
    void appendDevlog({
      title: 'Production Rollback Executed',
      authorHandle: '@release-lead',
      targetHandle: '@all-agents',
      branch: state.bundle.targetBranch,
      summary: 'Reverted production traffic to atlas-chat@v2.3.9 snapshot.',
    });
  };

  const handlePostSwarmMessage = async (input: {
    channelId: SwarmChannelId;
    senderAgentId: string;
    targetHandle: string;
    kind: MessageKind;
    body: string;
    workstreamId?: string;
    alsoWriteDevlog?: boolean;
  }): Promise<SwarmChannelId | void> => {
    const slash = executeSwarmSlashCommand(
      state,
      input.body,
      input.channelId,
      input.senderAgentId
    );
    if (slash.handled) {
      persistState(slash.state);
      if (slash.notice) flashNotice(slash.notice);
      if (slash.switchView) setActiveView(slash.switchView);
      if (input.alsoWriteDevlog) {
        const sender = state.agents.find((a) => a.id === input.senderAgentId);
        await appendDevlog({
          title: `Swarm Command (${input.body.trim().slice(0, 42)})`,
          authorHandle: sender?.handle ?? '@release-lead',
          targetHandle: '@all-agents',
          summary: slash.notice ?? input.body,
        });
      }
      return slash.switchChannel;
    }

    const next = postSwarmMessage(state, input);
    persistState(next);

    if (input.alsoWriteDevlog) {
      const sender = state.agents.find((a) => a.id === input.senderAgentId);
      const ws = input.workstreamId
        ? state.workstreams.find((w) => w.id === input.workstreamId)
        : undefined;
      await appendDevlog({
        title: `Swarm Update (#${input.channelId})`,
        authorHandle: sender?.handle ?? '@release-lead',
        targetHandle: input.targetHandle,
        branch: ws?.branch,
        summary: input.body,
      });
    }
  };

  const handleCtfBroadcast = (message: string) => {
    void handlePostSwarmMessage({
      channelId: 'atlas-integration',
      senderAgentId: 'agent-lead',
      targetHandle: '@all-agents',
      kind: 'handoff',
      body: message,
      workstreamId: 'ws-nightmare-ctf',
      alsoWriteDevlog: true,
    });
    setActiveView('swarm');
  };

  const handleAcknowledgeMessage = (messageId: string) => {
    persistState(acknowledgeSwarmMessage(state, messageId));
  };

  const handleRunGeminiAudit = async () => {
    setAuditLoading(true);
    setAuditError(null);
    try {
      const res = await fetch('/api/gemini/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workstreams: state.workstreams.map((w) => ({
            branch: w.branch,
            provider: w.provider,
            gitState: w.gitState,
            conflictState: w.conflictState,
          })),
          features: state.features.map((f) => ({
            name: f.name,
            status: f.status,
            suite: f.suite,
          })),
          bundle: state.bundle,
          pipelineStatus: state.pipeline.status,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setAuditError(data?.error || 'Gemini preflight audit failed.');
        return;
      }
      const next: OrchestratorState = {
        ...state,
        pipeline: {
          ...state.pipeline,
          aiAuditReport: data.report,
          aiAuditGeneratedAt: data.generatedAt,
        },
      };
      persistState(next);
      flashNotice('Gemini preflight rollout audit completed.');
    } catch {
      setAuditError('Unable to reach server-side Gemini audit endpoint.');
    } finally {
      setAuditLoading(false);
    }
  };

  const handleRequestGeminiReply = async (channelId: SwarmChannelId) => {
    setGeminiReplyLoading(true);
    setGeminiReplyError(null);
    try {
      const recent = state.messages
        .filter((m) => m.channelId === channelId)
        .slice(-5)
        .map((m) => ({
          sender: m.senderAgentId,
          target: m.targetHandle,
          body: m.body,
        }));

      const res = await fetch('/api/gemini/swarm-reply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channelId,
          recentMessages: recent,
          summary: {
            uncommitted: readiness.uncommittedCount,
            conflicts: readiness.conflictCount,
            featuresVerified: `${readiness.featuresVerified}/${readiness.featuresTotal}`,
            pipelineStatus: state.pipeline.status,
          },
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setGeminiReplyError(data?.error || 'Gemini swarm reply failed.');
        return;
      }

      const next = postSwarmMessage(state, {
        channelId,
        senderAgentId: 'agent-gemini',
        targetHandle: '@all-agents',
        kind: 'verification',
        body: data.replyText,
        actionHistory: data.actionHistory,
      });
      persistState(next);
    } catch {
      setGeminiReplyError('Unable to reach server-side Gemini swarm reply endpoint.');
    } finally {
      setGeminiReplyLoading(false);
    }
  };

  // Contextual single primary CTA in TopBar
  const topBarAction = useMemo(() => {
    if (activeView === 'workstreams') {
      if (readiness.uncommittedCount > 0) {
        return {
          label: `Commit ${readiness.uncommittedCount} Uncommitted`,
          action: handleCommitAllUncommitted,
          disabled: false,
        };
      }
      return {
        label: 'Build Bundle',
        action: handleBuildBundle,
        disabled: !readiness.canConsolidate,
      };
    }

    if (activeView === 'pipeline') {
      if (state.pipeline.status === 'awaiting_approval') {
        return {
          label: 'Promote to Production',
          action: handlePromoteToProduction,
          disabled: false,
        };
      }
      return {
        label: 'Start Rollout',
        action: handleStartRollout,
        disabled: !readiness.canDeployToProd || state.pipeline.status === 'live',
      };
    }

    if (activeView === 'swarm') {
      return {
        label: 'Open Rollout Pipeline',
        action: () => setActiveView('pipeline'),
        disabled: false,
      };
    }

    if (activeView === 'ctf') {
      return {
        label: 'Open Swarm Board',
        action: () => setActiveView('swarm'),
        disabled: false,
      };
    }

    return {
      label: readiness.canDeployToProd ? 'Open Rollout Pipeline' : 'Inspect Workstreams',
      action: () => setActiveView(readiness.canDeployToProd ? 'pipeline' : 'workstreams'),
      disabled: false,
    };
  }, [activeView, readiness, state.pipeline.status]);

  return (
    <div className="flex min-h-screen bg-[#0D0F13] text-[#F3F4F6]">
      <Sidebar
        activeView={activeView}
        onNavigate={setActiveView}
        state={state}
        readiness={readiness}
        mobileOpen={mobileMenuOpen}
        onCloseMobile={() => setMobileMenuOpen(false)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          activeView={activeView}
          projectName={state.projectName}
          onNavigate={setActiveView}
          onOpenMobileMenu={() => setMobileMenuOpen(true)}
          primaryActionLabel={topBarAction.label}
          onPrimaryAction={topBarAction.action}
          primaryActionDisabled={topBarAction.disabled}
        />

        {statusNotice && (
          <div
            role="status"
            aria-live="polite"
            className="border-b border-blue-500/20 bg-blue-500/10 px-6 py-2 text-[12.5px] text-blue-200"
          >
            {statusNotice}
          </div>
        )}

        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {activeView === 'overview' && (
            <OverviewView
              state={state}
              readiness={readiness}
              onNavigate={setActiveView}
              onCommitAllUncommitted={handleCommitAllUncommitted}
              onVerifyAllIntegrated={handleVerifyAllIntegrated}
              onBuildBundle={handleBuildBundle}
            />
          )}

          {activeView === 'workstreams' && (
            <WorkstreamsView
              state={state}
              readiness={readiness}
              onCommitWorkstream={handleCommitWorkstream}
              onCommitAllUncommitted={handleCommitAllUncommitted}
              onResolveConflict={handleResolveConflict}
              onToggleSelection={handleToggleSelection}
              onAddWorkstream={handleAddWorkstream}
              onBuildBundle={handleBuildBundle}
            />
          )}

          {activeView === 'pipeline' && (
            <PipelineView
              state={state}
              readiness={readiness}
              onSetRolloutMode={handleSetRolloutMode}
              onVerifyFeature={handleVerifyFeature}
              onVerifyAllIntegrated={handleVerifyAllIntegrated}
              onStartRollout={handleStartRollout}
              onPromoteToProduction={handlePromoteToProduction}
              onRollback={handleRollback}
              onRunGeminiAudit={handleRunGeminiAudit}
              auditLoading={auditLoading}
              auditError={auditError}
            />
          )}

          {activeView === 'swarm' && (
            <SwarmBoardView
              state={state}
              devlogMarkdown={devlogMarkdown}
              onPostMessage={handlePostSwarmMessage}
              onAcknowledgeMessage={handleAcknowledgeMessage}
              onRequestGeminiReply={handleRequestGeminiReply}
              geminiReplyLoading={geminiReplyLoading}
              geminiReplyError={geminiReplyError}
            />
          )}

          {activeView === 'ctf' && (
            <CtfWorkbenchView onBroadcastToSwarm={handleCtfBroadcast} />
          )}
        </main>
      </div>
    </div>
  );
}
