import {
  ActionHistoryBlock,
  FeatureCheck,
  IntegrationBundle,
  LogSeverity,
  MessageKind,
  OrchestratorState,
  ProviderSource,
  ResolutionStrategy,
  RolloutPipeline,
  RunLogEntry,
  SwarmChannelId,
  SwarmMessage,
  TestSuiteResult,
  Workstream,
} from '../types/orchestrator';

export interface ReadinessSummary {
  totalWorkstreams: number;
  selectedCount: number;
  committedCount: number;
  uncommittedCount: number;
  conflictCount: number;
  featuresTotal: number;
  featuresMissing: number;
  featuresIntegrated: number;
  featuresVerified: number;
  canConsolidate: boolean;
  canDeployToProd: boolean;
  blockers: string[];
}

export function generateShortSha(seed: string): string {
  let hash = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(7, '0').slice(0, 7);
}

function formatClock(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '16:05:00';
  return date.toISOString().slice(11, 19);
}

function makeLog(
  stageId: RunLogEntry['stageId'],
  agentLabel: string,
  severity: LogSeverity,
  message: string,
  timestamp: string,
  detail?: string
): RunLogEntry {
  return {
    id: `log-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    timestamp: formatClock(timestamp),
    stageId,
    agentLabel,
    severity,
    message,
    detail,
  };
}

export function computeTestSuites(features: FeatureCheck[]): TestSuiteResult[] {
  const specs: Array<{ id: 'unit' | 'integration' | 'e2e'; label: string; command: string }> = [
    {
      id: 'unit',
      label: 'Unit Tests',
      command: 'pytest atlas-rust-desktop/validation-tests/test_optional_modules_and_compare.py && tsx --test',
    },
    {
      id: 'integration',
      label: 'Integration Tests',
      command: 'npm run test:integration -- --providers=google,chatgpt,local,hexstrike',
    },
    {
      id: 'e2e',
      label: 'End-to-End Tests',
      command: 'playwright test tests/e2e/atlas-swarm-rollout.spec.ts',
    },
  ];

  return specs.map((spec) => {
    const matching = features.filter((f) => f.suite === spec.id);
    const total = matching.reduce((sum, f) => sum + f.assertionsTotal, 0);
    const passed = matching.reduce((sum, f) => sum + f.assertionsPassed, 0);
    const hasMissing = matching.some((f) => f.status === 'missing');
    const allVerified = matching.length > 0 && matching.every((f) => f.status === 'verified');
    return {
      ...spec,
      total,
      passed,
      status: allVerified ? 'passed' : hasMissing ? 'blocked' : 'idle',
      durationSec: allVerified ? (spec.id === 'unit' ? 4.2 : spec.id === 'integration' ? 11.8 : 19.5) : null,
    };
  });
}

export function syncFeatureStatusesWithWorkstreams(
  features: FeatureCheck[],
  workstreams: Workstream[]
): FeatureCheck[] {
  const wsMap = new Map(workstreams.map((w) => [w.id, w]));
  return features.map((feat) => {
    const ws = wsMap.get(feat.workstreamId);
    if (!ws) return feat;

    const isIntegratedWorkstream =
      ws.gitState === 'committed' && ws.conflictState !== 'conflict';

    if (!isIntegratedWorkstream) {
      return {
        ...feat,
        status: 'missing',
      };
    }

    if (feat.status === 'missing') {
      return {
        ...feat,
        status: 'integrated',
        notes: `Integrated from ${ws.branch} (${ws.commitSha ?? 'staged'}). Ready for verification confirmation.`,
      };
    }

    return feat;
  });
}

export function computeReadiness(
  workstreams: Workstream[],
  features: FeatureCheck[]
): ReadinessSummary {
  const selected = workstreams.filter((w) => w.selectedForIntegration);
  const committedCount = selected.filter((w) => w.gitState === 'committed').length;
  const uncommittedCount = selected.filter((w) => w.gitState === 'uncommitted').length;
  const conflictCount = selected.filter((w) => w.conflictState === 'conflict').length;

  const featuresMissing = features.filter((f) => f.status === 'missing').length;
  const featuresIntegrated = features.filter((f) => f.status === 'integrated').length;
  const featuresVerified = features.filter((f) => f.status === 'verified').length;

  const blockers: string[] = [];
  if (selected.length === 0) {
    blockers.push('Select at least one workstream to build an integration bundle.');
  }
  if (uncommittedCount > 0) {
    blockers.push(`${uncommittedCount} uncommitted workstream${uncommittedCount > 1 ? 's' : ''} must be committed and staged.`);
  }
  if (conflictCount > 0) {
    blockers.push(`${conflictCount} merge conflict${conflictCount > 1 ? 's' : ''} must be resolved.`);
  }
  if (featuresMissing > 0) {
    blockers.push(`${featuresMissing} atlas-chat feature${featuresMissing > 1 ? 's are' : ' is'} still missing from integration.`);
  }
  if (featuresIntegrated > 0) {
    blockers.push(`${featuresIntegrated} integrated feature${featuresIntegrated > 1 ? 's need' : ' needs'} verification confirmation.`);
  }

  const canConsolidate = selected.length > 0 && uncommittedCount === 0 && conflictCount === 0;
  const canDeployToProd = canConsolidate && featuresMissing === 0 && featuresVerified === features.length;

  return {
    totalWorkstreams: workstreams.length,
    selectedCount: selected.length,
    committedCount,
    uncommittedCount,
    conflictCount,
    featuresTotal: features.length,
    featuresMissing,
    featuresIntegrated,
    featuresVerified,
    canConsolidate,
    canDeployToProd,
    blockers,
  };
}

export function commitWorkstream(
  state: OrchestratorState,
  workstreamId: string,
  timestamp = new Date().toISOString()
): OrchestratorState {
  const target = state.workstreams.find((w) => w.id === workstreamId);
  if (!target || target.gitState === 'committed') return state;

  const sha = generateShortSha(`${target.branch}:${timestamp}`);
  const workstreams = state.workstreams.map((w) =>
    w.id === workstreamId
      ? {
          ...w,
          gitState: 'committed' as const,
          commitSha: sha,
          upstreamStatus: `origin/${w.branch} [staged ${sha}]`,
          updatedAt: timestamp,
          files: w.files.map((f) =>
            f.status === 'untracked' ? { ...f, status: 'added' as const } : f
          ),
        }
      : w
  );

  const features = syncFeatureStatusesWithWorkstreams(state.features, workstreams);
  const agent = state.agents.find((a) => a.id === target.agentId);

  const actionHistory: ActionHistoryBlock = {
    modelName: agent?.modelLabel ?? 'Atlas Git Runner',
    durationLabel: 'Completed in 0.9s',
    summary: `Committed & staged ${target.branch} at ${sha}:`,
    groups: [
      {
        kind: 'git',
        heading: `Committed ${target.files.length} file${target.files.length === 1 ? '' : 's'}`,
        items: target.files.map((f) => ({
          label: f.path,
          status: 'done' as const,
          meta: `+${f.additions} / -${f.deletions}`,
        })),
      },
    ],
  };

  const systemMsg: SwarmMessage = {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    channelId: 'atlas-integration',
    senderAgentId: target.agentId,
    targetHandle: '@release-lead',
    kind: 'patch_ready',
    body: `Committed & staged ${target.branch} at ${sha}. Working tree is clean and linked atlas-chat features moved to Integrated.`,
    workstreamId: target.id,
    actionHistory,
    acknowledged: false,
    createdAt: timestamp,
  };

  return {
    ...state,
    workstreams,
    features,
    pipeline: {
      ...state.pipeline,
      testSuites: computeTestSuites(features),
      runLog: [
        ...state.pipeline.runLog,
        makeLog(
          'consolidate',
          agent?.displayName ?? 'Git Runner',
          'milestone',
          `Committed ${target.branch} at ${sha} (${target.files.length} files staged).`,
          timestamp
        ),
      ],
    },
    messages: [...state.messages, systemMsg],
  };
}

export function commitAllUncommitted(
  state: OrchestratorState,
  timestamp = new Date().toISOString()
): OrchestratorState {
  let next = state;
  for (const ws of state.workstreams) {
    if (ws.gitState === 'uncommitted') {
      next = commitWorkstream(next, ws.id, timestamp);
    }
  }
  return next;
}

export function resolveConflict(
  state: OrchestratorState,
  workstreamId: string,
  strategy: ResolutionStrategy,
  timestamp = new Date().toISOString()
): OrchestratorState {
  const target = state.workstreams.find((w) => w.id === workstreamId);
  if (!target || target.conflictState !== 'conflict') return state;

  const workstreams = state.workstreams.map((w) =>
    w.id === workstreamId
      ? {
          ...w,
          conflictState: 'resolved' as const,
          resolutionStrategy: strategy,
          upstreamStatus: `origin/${w.branch} [resolved]`,
          updatedAt: timestamp,
          files: w.files.map((f) =>
            f.status === 'conflicted' ? { ...f, status: 'modified' as const } : f
          ),
        }
      : w
  );

  const features = syncFeatureStatusesWithWorkstreams(state.features, workstreams);

  const actionHistory: ActionHistoryBlock = {
    modelName: 'Swarm Lead · Git Resolver',
    durationLabel: 'Completed in 0.4s',
    summary: `Resolved merge conflict using "${strategy}" strategy:`,
    groups: [
      {
        kind: 'git',
        heading: 'Updated conflicted paths',
        items: target.files.map((f) => ({
          label: f.path,
          status: 'done' as const,
          meta: strategy,
        })),
      },
    ],
  };

  const resolvedMsg: SwarmMessage = {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    channelId: 'merge-conflicts',
    senderAgentId: 'agent-lead',
    targetHandle: '@all-agents',
    kind: 'verification',
    body: `Resolved merge conflict on ${target.branch} using "${strategy}" strategy. Both Google Chat/Gemini and ChatGPT adapters are cleanly registered.`,
    workstreamId: target.id,
    actionHistory,
    acknowledged: true,
    createdAt: timestamp,
  };

  return {
    ...state,
    workstreams,
    features,
    pipeline: {
      ...state.pipeline,
      testSuites: computeTestSuites(features),
      runLog: [
        ...state.pipeline.runLog,
        makeLog(
          'consolidate',
          'Git Gate',
          'milestone',
          `Resolved merge conflict on ${target.branch} (${strategy} strategy).`,
          timestamp
        ),
      ],
    },
    messages: [...state.messages, resolvedMsg],
  };
}

export function toggleWorkstreamSelection(
  state: OrchestratorState,
  workstreamId: string
): OrchestratorState {
  return {
    ...state,
    workstreams: state.workstreams.map((w) =>
      w.id === workstreamId
        ? { ...w, selectedForIntegration: !w.selectedForIntegration }
        : w
    ),
  };
}

export function addWorkstream(
  state: OrchestratorState,
  input: {
    title: string;
    branch: string;
    provider: ProviderSource;
    gitState: 'committed' | 'uncommitted';
    summary: string;
    filePath: string;
  },
  timestamp = new Date().toISOString()
): OrchestratorState {
  const id = `ws-${input.provider}-${Date.now().toString(36)}`;
  const agentMap: Record<ProviderSource, string> = {
    google: 'agent-gemini',
    chatgpt: 'agent-chatgpt',
    local: 'agent-local',
  };

  const newWs: Workstream = {
    id,
    title: input.title.trim(),
    branch: input.branch.trim(),
    upstreamStatus: input.gitState === 'committed' ? `origin/${input.branch.trim()} [synced]` : 'local working tree [uncommitted]',
    provider: input.provider,
    agentId: agentMap[input.provider],
    gitState: input.gitState,
    commitSha: input.gitState === 'committed' ? generateShortSha(`${input.branch}:${timestamp}`) : null,
    conflictState: 'clean',
    selectedForIntegration: true,
    linkedFeatureIds: [],
    updatedAt: timestamp,
    summary: input.summary.trim(),
    files: [
      {
        path: input.filePath.trim() || `src/${input.provider}/patch.ts`,
        additions: 48,
        deletions: 6,
        status: input.gitState === 'committed' ? 'modified' : 'untracked',
        preview: `+ # Registered workstream for atlas-chat (${input.provider})\n+ export const patchReady = true;`,
      },
    ],
  };

  return {
    ...state,
    workstreams: [newWs, ...state.workstreams],
  };
}

export function verifyFeature(
  state: OrchestratorState,
  featureId: string,
  timestamp = new Date().toISOString()
): OrchestratorState {
  const target = state.features.find((f) => f.id === featureId);
  if (!target || target.status === 'missing') return state;

  const features = state.features.map((f) =>
    f.id === featureId
      ? {
          ...f,
          status: 'verified' as const,
          assertionsPassed: f.assertionsTotal,
          lastVerifiedAt: timestamp,
          notes: `Confirmed working (${f.assertionsTotal}/${f.assertionsTotal} ${f.suite} assertions passed).`,
        }
      : f
  );

  return {
    ...state,
    features,
    pipeline: {
      ...state.pipeline,
      testSuites: computeTestSuites(features),
      runLog: [
        ...state.pipeline.runLog,
        makeLog(
          'verify',
          'Test Runner',
          'routine',
          `Confirmed ${target.name} (${target.assertionsTotal}/${target.assertionsTotal} ${target.suite} checks passed).`,
          timestamp
        ),
      ],
    },
  };
}

export function verifyAllIntegratedFeatures(
  state: OrchestratorState,
  timestamp = new Date().toISOString()
): OrchestratorState {
  const newlyVerified: FeatureCheck[] = [];
  const features = state.features.map((f) => {
    if (f.status === 'integrated') {
      const updated: FeatureCheck = {
        ...f,
        status: 'verified',
        assertionsPassed: f.assertionsTotal,
        lastVerifiedAt: timestamp,
        notes: `Confirmed working (${f.assertionsTotal}/${f.assertionsTotal} ${f.suite} assertions passed).`,
      };
      newlyVerified.push(updated);
      return updated;
    }
    return f;
  });

  if (newlyVerified.length === 0) return state;

  const actionHistory: ActionHistoryBlock = {
    modelName: 'Atlas Verification Matrix',
    durationLabel: 'Completed in 3.2s',
    summary: `Confirmed ${newlyVerified.length} integrated features across Unit, Integration & E2E suites:`,
    groups: [
      {
        kind: 'test',
        heading: `Verified ${newlyVerified.length} feature checks`,
        items: newlyVerified.map((f) => ({
          label: f.name,
          status: 'done' as const,
          meta: `${f.assertionsTotal}/${f.assertionsTotal} ${f.suite}`,
        })),
      },
    ],
  };

  const verifyMsg: SwarmMessage = {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    channelId: 'missing-features',
    senderAgentId: 'agent-local',
    targetHandle: '@release-lead',
    kind: 'verification',
    body: `All ${newlyVerified.length} newly integrated atlas-chat features passed automated verification and are confirmed working.`,
    actionHistory,
    acknowledged: true,
    createdAt: timestamp,
  };

  return {
    ...state,
    features,
    pipeline: {
      ...state.pipeline,
      testSuites: computeTestSuites(features),
      runLog: [
        ...state.pipeline.runLog,
        makeLog(
          'verify',
          'Test Matrix',
          'milestone',
          `Verified ${newlyVerified.length} integrated features across unit, integration, and E2E suites.`,
          timestamp
        ),
      ],
    },
    messages: [...state.messages, verifyMsg],
  };
}

export function buildIntegrationBundle(
  state: OrchestratorState,
  timestamp = new Date().toISOString()
): { state: OrchestratorState; ok: boolean; error?: string } {
  const readiness = computeReadiness(state.workstreams, state.features);
  if (!readiness.canConsolidate) {
    return {
      state,
      ok: false,
      error: readiness.blockers[0] || 'Resolve uncommitted work and conflicts before building bundle.',
    };
  }

  const selected = state.workstreams.filter((w) => w.selectedForIntegration);
  const totalFiles = selected.reduce((sum, w) => sum + w.files.length, 0);
  const totalAdditions = selected.reduce(
    (sum, w) => sum + w.files.reduce((s, f) => s + f.additions, 0),
    0
  );
  const totalDeletions = selected.reduce(
    (sum, w) => sum + w.files.reduce((s, f) => s + f.deletions, 0),
    0
  );
  const providersIncluded = Array.from(new Set(selected.map((w) => w.provider)));

  const bundle: IntegrationBundle = {
    version: 'atlas-chat@v2.4.0-rc.2',
    targetBranch: 'integration/atlas-chat-v2.4.0',
    baseBranch: state.repoBranch,
    workstreamIds: selected.map((w) => w.id),
    createdAt: timestamp,
    totalFiles,
    totalAdditions,
    totalDeletions,
    providersIncluded,
    isReady: true,
  };

  const actionHistory: ActionHistoryBlock = {
    modelName: 'Swarm Lead · Release Builder',
    durationLabel: 'Completed in 2.6s',
    summary: `Consolidated ${selected.length} branches into ${bundle.version}:`,
    groups: [
      {
        kind: 'git',
        heading: `Merged ${selected.length} workstreams (${totalFiles} files)`,
        items: selected.map((w) => ({
          label: w.branch,
          status: 'done' as const,
          meta: w.commitSha ?? 'staged',
        })),
      },
    ],
  };

  const bundleMsg: SwarmMessage = {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    channelId: 'prod-rollout',
    senderAgentId: 'agent-lead',
    targetHandle: '@all-agents',
    kind: 'directive',
    body: `Consolidated ${selected.length} workstreams (${providersIncluded.join(', ')}) into ${bundle.version} (+${totalAdditions}/-${totalDeletions}). Ready for final test confirmation and staged rollout.`,
    actionHistory,
    acknowledged: true,
    createdAt: timestamp,
  };

  return {
    ok: true,
    state: {
      ...state,
      bundle,
      pipeline: {
        ...state.pipeline,
        runLog: [
          ...state.pipeline.runLog,
          makeLog(
            'consolidate',
            'Release Builder',
            'milestone',
            `Built unified integration bundle ${bundle.version} (${selected.length} branches, ${totalFiles} files).`,
            timestamp
          ),
        ],
      },
      messages: [...state.messages, bundleMsg],
    },
  };
}

export function startRolloutPipeline(
  state: OrchestratorState,
  timestamp = new Date().toISOString()
): { state: OrchestratorState; ok: boolean; error?: string } {
  const readiness = computeReadiness(state.workstreams, state.features);
  if (!readiness.canDeployToProd) {
    return {
      state,
      ok: false,
      error: readiness.blockers[0] || 'Complete all integration & feature checks before rollout.',
    };
  }

  const selectedCount = state.workstreams.filter((w) => w.selectedForIntegration).length;
  const totalAssertions = state.features.reduce((sum, f) => sum + f.assertionsTotal, 0);

  const pipeline: RolloutPipeline = {
    ...state.pipeline,
    runId: `run-${Date.now().toString().slice(-4)}`,
    status: 'awaiting_approval',
    canaryPercent: 50,
    startedAt: timestamp,
    completedAt: null,
    testSuites: computeTestSuites(state.features),
    stages: [
      {
        id: 'consolidate',
        name: 'Git Consolidation & Build',
        description: 'Stage untracked atlas-chat files, merge Google Chat/Gemini, ChatGPT, and Local branches, and compile release artifacts.',
        status: 'passed',
        durationSec: 14,
        logs: [
          `[1/3] Verified clean working tree across ${selectedCount} selected atlas-chat workstreams.`,
          `[2/3] Merged Google Chat/Gemini, ChatGPT, and Local commits into ${state.bundle.targetBranch}.`,
          `[3/3] Built Tauri desktop resources, Python modules, and web bundle for ${state.bundle.version}.`,
        ],
      },
      {
        id: 'verify',
        name: 'Automated Test Matrix (Unit · Integration · E2E)',
        description: `Execute all ${totalAssertions} assertions across compare_mode.py, optional_modules.py, hexstrike-ai, provider adapters, and E2E chat flows.`,
        status: 'passed',
        durationSec: 35,
        logs: [
          `[1/3] Unit Suite passed: compare_mode.py, optional_modules.py, and compactor tests green.`,
          `[2/3] Integration Suite passed: Google Chat, ChatGPT, Local Ollama, and hexstrike-ai contracts verified.`,
          `[3/3] E2E Suite passed: ${totalAssertions}/${totalAssertions} total assertions confirmed working.`,
        ],
      },
      {
        id: 'canary',
        name: 'Staged Canary Rollout (10% → 50%)',
        description: 'Shift live traffic across Google Chat, ChatGPT, and Local runners with error-budget guardrails and manual approval gate.',
        status: 'awaiting_approval',
        durationSec: 42,
        logs: [
          '[1/3] Shifted 10% → 50% atlas-chat traffic to canary pods.',
          '[2/3] Streaming TTFT p95: 184ms (budget < 300ms). Error rate: 0.01% (budget < 0.1%).',
          '[3/3] Awaiting Release Lead sign-off to promote to 100% Production.',
        ],
      },
      {
        id: 'production',
        name: 'Production Cutover (100%)',
        description: 'Tag atlas-chat@v2.4.0-prod globally and pin instant rollback snapshot to v2.3.9.',
        status: 'idle',
        durationSec: null,
        logs: ['Ready for Release Lead approval at Canary Gate.'],
      },
    ],
    runLog: [
      ...state.pipeline.runLog,
      makeLog('consolidate', 'CI Builder', 'milestone', `Compiled ${state.bundle.version} with zero git drift.`, timestamp),
      makeLog('verify', 'Test Matrix', 'milestone', `Unit, Integration, and E2E suites passed (${totalAssertions}/${totalAssertions} assertions).`, timestamp),
      makeLog('canary', 'Rollout Gate', 'milestone', 'Canary traffic at 50% healthy (0.01% error rate). Waiting for Release Lead approval.', timestamp),
    ],
  };

  const actionHistory: ActionHistoryBlock = {
    modelName: 'Gemini 4 Neon · Rollout Controller',
    durationLabel: 'Ran for 1m 31s',
    summary: 'Here are key actions taken in the staged rollout pipeline:',
    groups: [
      {
        kind: 'test',
        heading: `Passed 3 automated test suites (${totalAssertions} assertions)`,
        items: [
          { label: 'Unit Tests (compare_mode + optional_modules + compactor)', status: 'done', meta: '38/38' },
          { label: 'Integration Tests (Google + ChatGPT + Local + HexStrike)', status: 'done', meta: '65/65' },
          { label: 'End-to-End Tests (Swarm Board & Action History UI)', status: 'done', meta: '34/34' },
        ],
      },
      {
        kind: 'deploy',
        heading: 'Canary rollout staged at 50% traffic',
        items: [
          { label: 'Canary Gate Approval', status: 'pending', meta: 'Awaiting sign-off' },
        ],
      },
    ],
  };

  const rolloutMsg: SwarmMessage = {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    channelId: 'prod-rollout',
    senderAgentId: 'agent-gemini',
    targetHandle: '@release-lead',
    kind: 'handoff',
    body: `Automated build and Unit/Integration/E2E suites passed (${totalAssertions}/${totalAssertions}). Canary at 50% is nominal—ready for 100% production promotion.`,
    actionHistory,
    acknowledged: false,
    createdAt: timestamp,
  };

  return {
    ok: true,
    state: {
      ...state,
      pipeline,
      messages: [...state.messages, rolloutMsg],
    },
  };
}

export function promoteToProduction(
  state: OrchestratorState,
  timestamp = new Date().toISOString()
): OrchestratorState {
  if (state.pipeline.status !== 'awaiting_approval') return state;

  const pipeline: RolloutPipeline = {
    ...state.pipeline,
    status: 'live',
    canaryPercent: 100,
    completedAt: timestamp,
    stages: state.pipeline.stages.map((stage) => {
      if (stage.id === 'canary') {
        return {
          ...stage,
          status: 'passed',
          logs: [...stage.logs, '[approved] Release Lead approved canary gate.'],
        };
      }
      if (stage.id === 'production') {
        return {
          ...stage,
          status: 'passed',
          durationSec: 19,
          logs: [
            '[1/3] Promoted atlas-chat@v2.4.0-prod to 100% global production traffic.',
            '[2/3] Synchronized Google Chat/Gemini, ChatGPT, Local Ollama, and HexStrike adapters.',
            '[3/3] Rollback snapshot pinned to atlas-chat@v2.3.9.',
          ],
        };
      }
      return stage;
    }),
    runLog: [
      ...state.pipeline.runLog,
      makeLog('production', 'Release Controller', 'milestone', 'Promoted atlas-chat@v2.4.0-prod to 100% global production traffic.', timestamp),
    ],
  };

  const actionHistory: ActionHistoryBlock = {
    modelName: 'Swarm Lead · Production Cutover',
    durationLabel: 'Completed in 19s',
    summary: 'Here are key actions taken for production deployment:',
    groups: [
      {
        kind: 'deploy',
        heading: 'Promoted atlas-chat@v2.4.0-prod globally',
        items: [
          { label: 'Google Chat & Gemini Router', status: 'done', meta: '100% traffic' },
          { label: 'ChatGPT Provider Bridge & Branching', status: 'done', meta: '100% traffic' },
          { label: 'Local Ollama, Compare Mode & HexStrike AI', status: 'done', meta: '100% traffic' },
          { label: 'Rollback Snapshot (atlas-chat@v2.3.9)', status: 'done', meta: 'armed' },
        ],
      },
    ],
  };

  const prodMsg: SwarmMessage = {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    channelId: 'prod-rollout',
    senderAgentId: 'agent-lead',
    targetHandle: '@all-agents',
    kind: 'verification',
    body: 'atlas-chat@v2.4.0-prod is now live at 100% production traffic. All 10 features confirmed working and rollback snapshot armed.',
    actionHistory,
    acknowledged: true,
    createdAt: timestamp,
  };

  return {
    ...state,
    pipeline,
    messages: [...state.messages, prodMsg],
  };
}

export function rollbackProduction(
  state: OrchestratorState,
  reason = 'Manual release-lead rollback triggered',
  timestamp = new Date().toISOString()
): OrchestratorState {
  if (state.pipeline.status !== 'live' && state.pipeline.status !== 'awaiting_approval') {
    return state;
  }

  const pipeline: RolloutPipeline = {
    ...state.pipeline,
    status: 'rolled_back',
    canaryPercent: 0,
    completedAt: timestamp,
    stages: state.pipeline.stages.map((stage) =>
      stage.id === 'production' || stage.id === 'canary'
        ? {
            ...stage,
            status: 'rolled_back',
            logs: [...stage.logs, `[rollback] ${reason}. Reverted traffic to atlas-chat@v2.3.9.`],
          }
        : stage
    ),
    runLog: [
      ...state.pipeline.runLog,
      makeLog('production', 'Rollback Guard', 'problem', `Rolled back to atlas-chat@v2.3.9: ${reason}.`, timestamp),
    ],
  };

  const rbMsg: SwarmMessage = {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    channelId: 'prod-rollout',
    senderAgentId: 'agent-lead',
    targetHandle: '@all-agents',
    kind: 'conflict_alert',
    body: `Production rollback executed: ${reason}. Traffic safely restored to atlas-chat@v2.3.9.`,
    acknowledged: false,
    createdAt: timestamp,
  };

  return {
    ...state,
    pipeline,
    messages: [...state.messages, rbMsg],
  };
}

export function setRolloutMode(
  state: OrchestratorState,
  rolloutMode: 'hotsync' | 'full_installer'
): OrchestratorState {
  return {
    ...state,
    pipeline: {
      ...state.pipeline,
      rolloutMode,
    },
  };
}

export function postSwarmMessage(
  state: OrchestratorState,
  input: {
    channelId: SwarmChannelId;
    senderAgentId: string;
    targetHandle: string;
    kind: MessageKind;
    body: string;
    workstreamId?: string;
    actionHistory?: ActionHistoryBlock;
  },
  timestamp = new Date().toISOString()
): OrchestratorState {
  const trimmed = input.body.trim();
  if (!trimmed) return state;

  const sender = state.agents.find((a) => a.id === input.senderAgentId);
  const linkedWs = input.workstreamId
    ? state.workstreams.find((w) => w.id === input.workstreamId)
    : undefined;

  const autoActionHistory: ActionHistoryBlock | undefined =
    input.actionHistory ??
    (sender && (sender.provider !== 'human' || input.kind === 'devlog_sync')
      ? {
          modelName: sender.modelLabel,
          durationLabel: 'Completed in 0.8s',
          summary:
            input.kind === 'devlog_sync'
              ? 'Appended entry to DEVLOG.md and broadcasted across swarms:'
              : `Dispatched ${input.kind.replace('_', ' ')} to ${input.targetHandle}:`,
          groups: [
            {
              kind: input.kind === 'devlog_sync' ? 'edit' : linkedWs ? 'git' : 'edit',
              heading:
                input.kind === 'devlog_sync'
                  ? 'Updated 1 shared ledger file'
                  : linkedWs
                    ? `Referenced ${linkedWs.branch}`
                    : `Posted to #${input.channelId}`,
              items:
                input.kind === 'devlog_sync'
                  ? [
                      { label: 'DEVLOG.md', status: 'done' as const, meta: 'appended' },
                      ...(linkedWs
                        ? [{ label: linkedWs.branch, status: 'done' as const, meta: linkedWs.commitSha ?? 'staged' }]
                        : []),
                    ]
                  : linkedWs
                    ? linkedWs.files.slice(0, 3).map((f) => ({
                        label: f.path,
                        status: f.status === 'conflicted' ? ('problem' as const) : ('done' as const),
                        meta: `+${f.additions} / -${f.deletions}`,
                      }))
                    : [
                        {
                          label: `Delivered to ${input.targetHandle}`,
                          status: 'done' as const,
                          meta: input.kind.replace('_', ' '),
                        },
                      ],
            },
          ],
        }
      : undefined);

  const newMsg: SwarmMessage = {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    channelId: input.channelId,
    senderAgentId: input.senderAgentId,
    targetHandle: input.targetHandle,
    kind: input.kind,
    body: trimmed,
    workstreamId: input.workstreamId || undefined,
    actionHistory: autoActionHistory,
    acknowledged:
      input.kind === 'directive' ||
      input.kind === 'verification' ||
      input.kind === 'devlog_sync',
    createdAt: timestamp,
  };

  return {
    ...state,
    messages: [...state.messages, newMsg],
  };
}

export function acknowledgeSwarmMessage(
  state: OrchestratorState,
  messageId: string
): OrchestratorState {
  return {
    ...state,
    messages: state.messages.map((m) =>
      m.id === messageId ? { ...m, acknowledged: true } : m
    ),
  };
}

export function filterWorkstreams(
  workstreams: Workstream[],
  filters: {
    provider: ProviderSource | 'all';
    gitState: 'all' | 'committed' | 'uncommitted' | 'conflict';
    query: string;
  }
): Workstream[] {
  const q = filters.query.trim().toLowerCase();
  return workstreams.filter((w) => {
    if (filters.provider !== 'all' && w.provider !== filters.provider) return false;
    if (filters.gitState === 'committed' && w.gitState !== 'committed') return false;
    if (filters.gitState === 'uncommitted' && w.gitState !== 'uncommitted') return false;
    if (filters.gitState === 'conflict' && w.conflictState !== 'conflict') return false;
    if (q) {
      const hay = `${w.title} ${w.branch} ${w.summary} ${w.files.map((f) => f.path).join(' ')}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

export function filterSwarmMessages(
  messages: SwarmMessage[],
  filters: {
    channelId: SwarmChannelId;
    kind: MessageKind | 'all';
    query: string;
  }
): SwarmMessage[] {
  const q = filters.query.trim().toLowerCase();
  return messages.filter((m) => {
    if (m.channelId !== filters.channelId) return false;
    if (filters.kind !== 'all' && m.kind !== filters.kind) return false;
    if (q && !m.body.toLowerCase().includes(q) && !m.targetHandle.toLowerCase().includes(q)) {
      return false;
    }
    return true;
  });
}

export function filterRunLogs(
  logs: RunLogEntry[],
  mode: 'all' | 'hide_routine' | 'problems'
): RunLogEntry[] {
  if (mode === 'all') return logs;
  if (mode === 'problems') return logs.filter((l) => l.severity === 'problem');
  return logs.filter((l) => l.severity !== 'routine');
}

export interface SlashCommandResult {
  handled: boolean;
  state: OrchestratorState;
  switchChannel?: SwarmChannelId;
  switchView?: 'overview' | 'workstreams' | 'pipeline' | 'swarm' | 'ctf';
  notice?: string;
}

const VALID_CHANNELS: SwarmChannelId[] = [
  'atlas-integration',
  'missing-features',
  'merge-conflicts',
  'prod-rollout',
  'devlog-sync',
];

export function executeSwarmSlashCommand(
  state: OrchestratorState,
  rawText: string,
  channelId: SwarmChannelId,
  senderAgentId: string,
  timestamp = new Date().toISOString()
): SlashCommandResult {
  const trimmed = rawText.trim();
  if (!trimmed.startsWith('/swarm')) {
    return { handled: false, state };
  }

  const parts = trimmed.split(/\s+/);
  const sub = (parts[1] || 'help').toLowerCase();
  const arg = parts.slice(2).join(' ').trim();
  const sender = state.agents.find((a) => a.id === senderAgentId);

  if (sub === 'room' && arg) {
    const clean = arg.replace(/^#/, '') as SwarmChannelId;
    if (VALID_CHANNELS.includes(clean)) {
      const next = postSwarmMessage(
        state,
        {
          channelId: clean,
          senderAgentId,
          targetHandle: '@all-agents',
          kind: 'directive',
          body: `Switched active swarm room to #${clean} via /swarm room.`,
          actionHistory: {
            modelName: sender?.modelLabel ?? 'Swarm Controller',
            durationLabel: 'Completed in 0.2s',
            headerTitle: 'Action history',
            summary: 'Executed /swarm room command:',
            groups: [
              {
                kind: 'tool',
                heading: `Called tool · /swarm room ${clean}`,
                items: [{ label: `#${clean}`, status: 'done', meta: 'active room' }],
              },
            ],
          },
        },
        timestamp
      );
      return {
        handled: true,
        state: next,
        switchChannel: clean,
        notice: `Switched Swarm room to #${clean}.`,
      };
    }
  }

  if (sub === 'claim' && arg) {
    const agents = state.agents.map((a) =>
      a.id === senderAgentId ? { ...a, claimedTarget: arg } : a
    );
    const next = postSwarmMessage(
      { ...state, agents },
      {
        channelId,
        senderAgentId,
        targetHandle: '@all-agents',
        kind: 'handoff',
        body: `Claimed target "${arg}" via /swarm claim so peer sessions avoid duplicate work.`,
        actionHistory: {
          modelName: sender?.modelLabel ?? 'Swarm Controller',
          durationLabel: 'Completed in 0.2s',
          headerTitle: 'Action history',
          summary: 'Broadcasted live target claim across connected agents:',
          groups: [
            {
              kind: 'tool',
              heading: `Called tool · /swarm claim ${arg}`,
              items: [
                { label: arg, status: 'done', meta: `claimed by ${sender?.handle ?? '@agent'}` },
              ],
            },
          ],
        },
      },
      timestamp
    );
    return {
      handled: true,
      state: next,
      notice: `Claimed target "${arg}" in Swarm roster.`,
    };
  }

  if (sub === 'focus' && arg) {
    const targetView = arg.toLowerCase().includes('ctf') || arg.toLowerCase().startsWith('nm-')
      ? 'ctf'
      : arg.toLowerCase().includes('pipe') || arg.toLowerCase().includes('rollout')
        ? 'pipeline'
        : 'workstreams';

    const next = postSwarmMessage(
      state,
      {
        channelId,
        senderAgentId,
        targetHandle: '@all-agents',
        kind: 'directive',
        body: `Focused swarm session onto "${arg}" (${targetView === 'ctf' ? '/ctf' : targetView}) via /swarm focus.`,
        actionHistory: {
          modelName: sender?.modelLabel ?? 'Swarm Controller',
          durationLabel: 'Completed in 0.2s',
          headerTitle: 'Action history',
          summary: 'Broadcasted session focus event:',
          groups: [
            {
              kind: 'tool',
              heading: `Called tool · /swarm focus ${arg}`,
              items: [{ label: `Target view: ${targetView}`, status: 'done', meta: arg }],
            },
          ],
        },
      },
      timestamp
    );
    return {
      handled: true,
      state: next,
      switchView: targetView,
      notice: `Focused view on ${arg}.`,
    };
  }

  if (sub === 'status') {
    const readiness = computeReadiness(state.workstreams, state.features);
    const next = postSwarmMessage(
      state,
      {
        channelId,
        senderAgentId,
        targetHandle: '@all-agents',
        kind: 'verification',
        body: `Conduit status: ${readiness.committedCount}/${readiness.selectedCount} workstreams committed, ${readiness.conflictCount} conflicts, ${readiness.featuresVerified}/${readiness.featuresTotal} features verified, rollout ${state.pipeline.canaryPercent}%.`,
        actionHistory: {
          modelName: 'Conduit Swarm Controller',
          durationLabel: 'Completed in 0.1s',
          headerTitle: 'Action history',
          summary: 'Collected live atlas-chat orchestration telemetry:',
          groups: [
            {
              kind: 'test',
              heading: 'Current readiness snapshot',
              items: [
                {
                  label: 'Committed workstreams',
                  status: readiness.uncommittedCount === 0 ? 'done' : 'pending',
                  meta: `${readiness.committedCount}/${readiness.selectedCount}`,
                },
                {
                  label: 'Features confirmed working',
                  status: readiness.featuresVerified === readiness.featuresTotal ? 'done' : 'pending',
                  meta: `${readiness.featuresVerified}/${readiness.featuresTotal}`,
                },
                {
                  label: 'Atlas CTF (/ctf) module',
                  status: 'done',
                  meta: 'noprivacynofreedom/nightmare',
                },
              ],
            },
          ],
        },
      },
      timestamp
    );
    return { handled: true, state: next, notice: 'Posted live /swarm status snapshot.' };
  }

  // Default: /swarm help
  const helpState = postSwarmMessage(
    state,
    {
      channelId,
      senderAgentId: 'agent-gemini',
      targetHandle: sender?.handle ?? '@release-lead',
      kind: 'directive',
      body: 'Available Swarm commands: /swarm room <channel>, /swarm claim <target>, /swarm focus <nm-03|ctf|workstreams|pipeline>, /swarm status, /swarm help.',
      actionHistory: {
        modelName: 'Conduit Swarm Bridge',
        durationLabel: 'Completed in 0.1s',
        headerTitle: 'Action history',
        summary: 'Supported /swarm slash commands across atlas-chat & Atlas CTF:',
        groups: [
          {
            kind: 'tool',
            heading: 'Slash command reference',
            items: [
              { label: '/swarm room <channel>', status: 'done', meta: 'Switch room' },
              { label: '/swarm claim <target>', status: 'done', meta: 'Claim challenge/branch' },
              { label: '/swarm focus <target>', status: 'done', meta: 'Focus peer view' },
              { label: '/swarm status', status: 'done', meta: 'Post live readiness' },
            ],
          },
        ],
      },
    },
    timestamp
  );
  return { handled: true, state: helpState, notice: 'Displayed /swarm command help.' };
}
