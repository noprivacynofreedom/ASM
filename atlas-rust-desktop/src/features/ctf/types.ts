export type UserRole = 'player' | 'organizer' | 'admin';
export type RequestedRole = 'none' | 'organizer';
export type UserStatus = 'active' | 'suspended';

export interface UserProfile {
  uid: string;
  handle: string;
  displayName: string;
  teamName: string;
  role: UserRole;
  requestedRole: RequestedRole;
  status: UserStatus;
  createdAt?: unknown;
  updatedAt?: unknown;
}

export type ChallengeCategory =
  | 'Reversing'
  | 'Stack'
  | 'ROP'
  | 'Format'
  | 'Heap'
  | 'Mitigations';

export type ChallengeDifficulty = 'Beginner' | 'Intermediate' | 'Advanced';

export interface ChallengeMitigations {
  nx: string;
  pie: string;
  canary: string;
  relro: string;
}

export interface StackSimulationPreset {
  bufSize: number;
  savedRbpOffset: number;
  retOffset: number;
  targetAddr: string;
  targetSymbol: string;
}

export interface Challenge {
  id: string;
  moduleNum: string;
  moduleName: string;
  title: string;
  category: ChallengeCategory;
  difficulty: ChallengeDifficulty;
  arch: string;
  points: number;
  summary: string;
  objective: string;
  zipPath: string;
  flagHash: string;
  flagHint: string;
  published: boolean;
  mitigations: ChallengeMitigations;
  exploitTemplate: string;
  authorUid: string;
  createdAt?: unknown;
  updatedAt?: unknown;
  // Client-only UI augmentation (never written to Firestore)
  stackPreset?: StackSimulationPreset;
  sampleFlag?: string;
}

export type ProgressStatus = 'unsolved' | 'in_progress' | 'solved';

export interface UserProgress {
  id: string;
  uid: string;
  handle: string;
  challengeId: string;
  status: ProgressStatus;
  notes: string;
  pointsEarned: number;
  createdAt?: unknown;
  updatedAt?: unknown;
}

export interface ZipEntryItem {
  path: string;
  name: string;
  dir: boolean;
  size: number;
  bytes?: Uint8Array;
  text?: string;
  isElf?: boolean;
}

export interface ParsedElfInfo {
  valid: boolean;
  bitness: '32-bit' | '64-bit';
  endianness: 'Little Endian' | 'Big Endian';
  type: string;
  machine: string;
  entryPoint: string;
  programHeaderCount: number;
  sectionHeaderCount: number;
  nx: 'Enabled' | 'Disabled' | 'Unknown';
  pie: 'Enabled' | 'No PIE' | 'Unknown';
  relro: 'Partial / Full' | 'No RELRO' | 'Unknown';
}

export type WorkspaceView =
  | 'curriculum'
  | 'archive'
  | 'tooling'
  | 'swarm'
  | 'admin';

export interface SwarmPeer {
  sessionId: string;
  uid: string;
  handle: string;
  role: UserRole;
  activeView: WorkspaceView;
  activeChallengeId: string | null;
  joinedAt: number;
}

export interface SwarmClaim {
  challengeId: string;
  sessionId: string;
  handle: string;
  claimedAt: number;
}

export interface SwarmSharedNote {
  challengeId: string;
  content: string;
  updatedBy: string;
  updatedAt: number;
}

export interface SwarmArchiveManifest {
  fileName: string;
  fileCount: number;
  sharedBy: string;
  paths: string[];
  sharedAt: number;
}

export interface SwarmFeedItem {
  id: string;
  type: 'join' | 'leave' | 'message' | 'claim' | 'flag' | 'archive' | 'focus';
  handle: string;
  role: UserRole;
  text: string;
  challengeId?: string;
  timestamp: number;
}

export interface SwarmRoomState {
  roomId: string;
  peers: SwarmPeer[];
  claims: Record<string, SwarmClaim>;
  sharedNotes: Record<string, SwarmSharedNote>;
  archiveManifest: SwarmArchiveManifest | null;
  feed: SwarmFeedItem[];
}
