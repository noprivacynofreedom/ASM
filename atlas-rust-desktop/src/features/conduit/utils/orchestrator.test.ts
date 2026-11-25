import test from 'node:test';
import assert from 'node:assert/strict';
import { createInitialState } from '../data/seedData';
import {
  acknowledgeSwarmMessage,
  addWorkstream,
  buildIntegrationBundle,
  commitAllUncommitted,
  commitWorkstream,
  computeReadiness,
  filterRunLogs,
  filterSwarmMessages,
  filterWorkstreams,
  postSwarmMessage,
  promoteToProduction,
  resolveConflict,
  rollbackProduction,
  startRolloutPipeline,
  verifyAllIntegratedFeatures,
} from './orchestrator';

test('initial atlas-chat state flags uncommitted work, merge conflict, and missing features as rollout blockers', () => {
  const state = createInitialState();
  const readiness = computeReadiness(state.workstreams, state.features);

  assert.equal(readiness.uncommittedCount, 3);
  assert.equal(readiness.conflictCount, 1);
  assert.equal(readiness.featuresMissing, 6);
  assert.equal(readiness.canConsolidate, false);
  assert.equal(readiness.canDeployToProd, false);
  assert.ok(readiness.blockers.length >= 3);
});

test('committing local hardening branch stages all 4 untracked paths and transitions linked features to integrated', () => {
  const state = createInitialState();
  const next = commitWorkstream(state, 'ws-local-hardening', '2026-11-20T16:10:00Z');

  const ws = next.workstreams.find((w) => w.id === 'ws-local-hardening');
  assert.equal(ws?.gitState, 'committed');
  assert.ok(ws?.commitSha && ws.commitSha.length === 7);
  assert.ok(ws?.files.every((f) => f.status !== 'untracked'));

  const compareFeat = next.features.find((f) => f.id === 'feat-compare-mode');
  const hexstrikeFeat = next.features.find((f) => f.id === 'feat-hexstrike');
  assert.equal(compareFeat?.status, 'integrated');
  assert.equal(hexstrikeFeat?.status, 'integrated');

  const lastMsg = next.messages[next.messages.length - 1];
  assert.ok(lastMsg.actionHistory, 'commit message should include Action History card');
  assert.equal(lastMsg.actionHistory?.groups[0].items?.length, 4);
});

test('end-to-end consolidation, feature confirmation, staged canary rollout, promotion, and rollback', () => {
  let state = createInitialState();

  // Attempting to build bundle before clearing blockers must fail
  const blockedBundle = buildIntegrationBundle(state);
  assert.equal(blockedBundle.ok, false);

  // Commit all uncommitted work and resolve ChatGPT registry conflict
  state = commitAllUncommitted(state, '2026-11-20T16:11:00Z');
  state = resolveConflict(state, 'ws-chatgpt-bridge', 'merged', '2026-11-20T16:12:00Z');

  // Now bundle consolidation succeeds
  const built = buildIntegrationBundle(state, '2026-11-20T16:13:00Z');
  assert.equal(built.ok, true);
  state = built.state;
  assert.equal(state.bundle.isReady, true);
  assert.deepEqual(state.bundle.providersIncluded.sort(), ['chatgpt', 'google', 'local']);

  // Deployment still blocked until integrated features are verified
  const blockedDeploy = startRolloutPipeline(state);
  assert.equal(blockedDeploy.ok, false);

  // Confirm all integrated features working
  state = verifyAllIntegratedFeatures(state, '2026-11-20T16:14:00Z');
  const readiness = computeReadiness(state.workstreams, state.features);
  assert.equal(readiness.featuresMissing, 0);
  assert.equal(readiness.featuresVerified, state.features.length);
  assert.equal(readiness.canDeployToProd, true);
  assert.ok(state.pipeline.testSuites.every((s) => s.status === 'passed'));

  // Start staged rollout -> pauses at Canary 50% approval gate
  const started = startRolloutPipeline(state, '2026-11-20T16:15:00Z');
  assert.equal(started.ok, true);
  state = started.state;
  assert.equal(state.pipeline.status, 'awaiting_approval');
  assert.equal(state.pipeline.canaryPercent, 50);

  // Promote to 100% production
  state = promoteToProduction(state, '2026-11-20T16:16:00Z');
  assert.equal(state.pipeline.status, 'live');
  assert.equal(state.pipeline.canaryPercent, 100);

  // Instant rollback
  state = rollbackProduction(state, 'Canary regression test', '2026-11-20T16:17:00Z');
  assert.equal(state.pipeline.status, 'rolled_back');
  assert.equal(state.pipeline.canaryPercent, 0);
});

test('swarm board messaging, Action History generation, acknowledgement, and run-log filtering', () => {
  let state = createInitialState();
  const initialCount = state.messages.length;

  state = postSwarmMessage(
    state,
    {
      channelId: 'merge-conflicts',
      senderAgentId: 'agent-gemini',
      targetHandle: '@chatgpt-integrator',
      kind: 'handoff',
      body: 'Confirmed merged provider registry map for atlas-chat.',
      workstreamId: 'ws-chatgpt-bridge',
    },
    '2026-11-20T16:18:00Z'
  );

  assert.equal(state.messages.length, initialCount + 1);
  const posted = state.messages[state.messages.length - 1];
  assert.equal(posted.acknowledged, false);
  assert.ok(posted.actionHistory, 'Non-human agent reply should render structured Action History block');

  state = acknowledgeSwarmMessage(state, posted.id);
  assert.equal(state.messages.find((m) => m.id === posted.id)?.acknowledged, true);

  const conflictMsgs = filterSwarmMessages(state.messages, {
    channelId: 'merge-conflicts',
    kind: 'all',
    query: 'registry',
  });
  assert.ok(conflictMsgs.length >= 2);

  const problemLogs = filterRunLogs(state.pipeline.runLog, 'problems');
  assert.equal(problemLogs.length, 1);
  assert.equal(problemLogs[0].severity, 'problem');

  state = addWorkstream(state, {
    title: 'Add local prompt cache',
    branch: 'feat/local-prompt-cache',
    provider: 'local',
    gitState: 'uncommitted',
    summary: 'Caches prompt prefixes locally.',
    filePath: 'src/cache/promptCache.ts',
  });
  const localUncommitted = filterWorkstreams(state.workstreams, {
    provider: 'local',
    gitState: 'uncommitted',
    query: 'cache',
  });
  assert.equal(localUncommitted.length, 1);
});

test('swarm slash commands support /swarm claim, /swarm room, /swarm focus ctf, and /swarm status', async () => {
  const { executeSwarmSlashCommand } = await import('./orchestrator');
  let state = createInitialState();

  const claimRes = executeSwarmSlashCommand(
    state,
    '/swarm claim nm-03-strings-lab',
    'atlas-integration',
    'agent-lead',
    '2026-11-20T16:33:00Z'
  );
  assert.equal(claimRes.handled, true);
  state = claimRes.state;
  assert.equal(
    state.agents.find((a) => a.id === 'agent-lead')?.claimedTarget,
    'nm-03-strings-lab'
  );

  const focusRes = executeSwarmSlashCommand(
    state,
    '/swarm focus nm-05-bof',
    'atlas-integration',
    'agent-lead',
    '2026-11-20T16:33:05Z'
  );
  assert.equal(focusRes.switchView, 'ctf');

  const roomRes = executeSwarmSlashCommand(
    focusRes.state,
    '/swarm room devlog-sync',
    'atlas-integration',
    'agent-lead',
    '2026-11-20T16:33:10Z'
  );
  assert.equal(roomRes.switchChannel, 'devlog-sync');
});
