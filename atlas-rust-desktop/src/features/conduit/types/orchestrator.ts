export type ProviderSource = 'google' | 'chatgpt' | 'local';

export type GitState = 'committed' | 'uncommitted';

export type ConflictState = 'clean' | 'conflict' | 'resolved';

export type ResolutionStrategy = 'ours' | 'theirs' | 'merged';

export type FeatureStatus = 'missing' | 'integrated' | 'verified';

export type PipelineStageId = 'consolidate' | 'verify' | 'canary' | 'production';

export type StageStatus = 'idle' | 'running' | 'awaiting_approval' | 'passed' | 'failed' | 'rolled_back';

export type SwarmChannelId = 'atlas-integration' | 'missing-features' | 'merge-conflicts' | 'prod-rollout' | 'devlog-sync';

export type RolloutMode = 'hotsync' | 'full_installer';

export type MessageKind = 'handoff' | 'patch_ready' | 'conflict_alert' | 'verification' | 'directive' | 'devlog_sync';

export type LogSeverity = 'routine' | 'milestone' | 'problem';

export interface DiffFile {
  path: string;
  additions: number;
  deletions: number;
  status: 'added' | 'modified' | 'deleted' | 'conflicted' | 'untracked';
  preview: string;
}

export interface Workstream {
  id: string;
  title: string;
  branch: string;
  upstreamStatus?: string;
  provider: ProviderSource;
  agentId: string;
  gitState: GitState;
  commitSha: string | null;
  conflictState: ConflictState;
  conflictDetail?: string;
  resolutionStrategy?: ResolutionStrategy;
  selectedForIntegration: boolean;
  files: DiffFile[];
  linkedFeatureIds: string[];
  updatedAt: string;
  summary: string;
}

export interface FeatureCheck {
  id: string;
  name: string;
  category: 'Core Routing' | 'Chat UX' | 'Local Runtime' | 'Security & Ops' | 'Swarm Bus';
  provider: ProviderSource;
  workstreamId: string;
  suite: 'unit' | 'integration' | 'e2e';
  status: FeatureStatus;
  assertionsTotal: number;
  assertionsPassed: number;
  lastVerifiedAt: string | null;
  notes: string;
}

export interface IntegrationBundle {
  version: string;
  targetBranch: string;
  baseBranch: string;
  workstreamIds: string[];
  createdAt: string | null;
  totalFiles: number;
  totalAdditions: number;
  totalDeletions: number;
  providersIncluded: ProviderSource[];
  isReady: boolean;
}

export interface RunLogEntry {
  id: string;
  timestamp: string;
  stageId: PipelineStageId | 'setup';
  agentLabel: string;
  severity: LogSeverity;
  message: string;
  detail?: string;
}

export interface TestSuiteResult {
  id: 'unit' | 'integration' | 'e2e';
  label: string;
  command: string;
  total: number;
  passed: number;
  status: 'idle' | 'passed' | 'blocked';
  durationSec: number | null;
}

export interface PipelineStage {
  id: PipelineStageId;
  name: string;
  description: string;
  status: StageStatus;
  durationSec: number | null;
  logs: string[];
}

export interface RolloutPipeline {
  runId: string;
  rolloutMode: RolloutMode;
  status: 'idle' | 'running' | 'awaiting_approval' | 'live' | 'rolled_back';
  canaryPercent: number;
  startedAt: string | null;
  completedAt: string | null;
  testSuites: TestSuiteResult[];
  stages: PipelineStage[];
  runLog: RunLogEntry[];
  aiAuditReport: string | null;
  aiAuditGeneratedAt: string | null;
}

export interface SwarmAgent {
  id: string;
  handle: string;
  displayName: string;
  modelLabel: string;
  provider: ProviderSource | 'human';
  role: string;
  activeBranch: string;
  syncStatus: 'Synced' | 'Dirty Tree' | 'Awaiting Review' | 'Active';
  claimedTarget?: string;
}

export interface ActionHistoryItem {
  label: string;
  status: 'done' | 'pending' | 'problem';
  meta?: string;
}

export interface ActionHistoryGroup {
  kind: 'tool' | 'read' | 'thought' | 'error' | 'install' | 'edit' | 'test' | 'git' | 'deploy';
  heading: string;
  traceId?: string;
  detail?: string;
  items?: ActionHistoryItem[];
}

export interface ActionHistoryBlock {
  modelName: string;
  durationLabel: string;
  headerTitle?: string;
  summary?: string;
  groups: ActionHistoryGroup[];
}

export interface SwarmMessage {
  id: string;
  channelId: SwarmChannelId;
  senderAgentId: string;
  targetHandle: string;
  kind: MessageKind;
  body: string;
  workstreamId?: string;
  actionHistory?: ActionHistoryBlock;
  acknowledged: boolean;
  createdAt: string;
}

export interface OrchestratorState {
  projectName: string;
  repoBranch: string;
  releaseTarget: string;
  workstreams: Workstream[];
  features: FeatureCheck[];
  bundle: IntegrationBundle;
  pipeline: RolloutPipeline;
  agents: SwarmAgent[];
  messages: SwarmMessage[];
}

export type ActiveView = 'overview' | 'workstreams' | 'pipeline' | 'swarm' | 'ctf';
