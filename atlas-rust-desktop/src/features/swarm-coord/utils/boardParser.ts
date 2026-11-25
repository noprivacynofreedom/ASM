export type TaskStatus = 'TODO' | 'CLAIMED' | 'IN_REVIEW' | 'DONE' | 'BLOCKED';

export interface BoardTask {
  id: string;
  title: string;
  status: TaskStatus;
  ownerSession: string;
  branch: string;
  ownedPaths: string[];
  dependsOn: string[];
}

export interface PathConflict {
  path: string;
  taskIds: [string, string];
  sessions: [string, string];
}

export interface NewBoardTaskDraft {
  id: string;
  title: string;
  branch: string;
  ownedPathsText: string;
  dependsOnText: string;
}

const VALID_STATUSES: TaskStatus[] = ['TODO', 'CLAIMED', 'IN_REVIEW', 'DONE', 'BLOCKED'];

function stripBackticks(value: string): string {
  return value.trim().replace(/^`+|`+$/g, '').trim();
}

function parseListCell(cell: string): string[] {
  const cleaned = cell.trim();
  if (!cleaned || cleaned === '—' || cleaned === '-' || cleaned.toLowerCase() === 'none') {
    return [];
  }
  return cleaned
    .split(',')
    .map((item) => stripBackticks(item))
    .filter(Boolean);
}

export function parseBoardMarkdown(raw: string): BoardTask[] {
  const lines = raw.replace(/\r\n/g, '\n').split('\n');
  const tasks: BoardTask[] = [];

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('|')) continue;

    const cells = trimmed
      .split('|')
      .slice(1, -1)
      .map((cell) => cell.trim());

    if (cells.length < 7) continue;
    if (cells[0] === 'ID' || /^:?-+:?$/.test(cells[0])) continue;

    const rawStatus = cells[2].toUpperCase() as TaskStatus;
    const status: TaskStatus = VALID_STATUSES.includes(rawStatus) ? rawStatus : 'TODO';

    tasks.push({
      id: cells[0],
      title: cells[1],
      status,
      ownerSession: cells[3] || 'unassigned',
      branch: stripBackticks(cells[4] || ''),
      ownedPaths: parseListCell(cells[5] || ''),
      dependsOn: parseListCell(cells[6] || ''),
    });
  }

  return tasks;
}

export function serializeBoardMarkdown(tasks: BoardTask[]): string {
  const rows = tasks.map((task) => {
    const branchCell = task.branch ? `\`${task.branch}\`` : '—';
    const pathsCell =
      task.ownedPaths.length > 0 ? task.ownedPaths.map((p) => `\`${p}\``).join(', ') : '—';
    const depsCell = task.dependsOn.length > 0 ? task.dependsOn.join(', ') : '—';
    return `| ${task.id} | ${task.title} | ${task.status} | ${task.ownerSession || 'unassigned'} | ${branchCell} | ${pathsCell} | ${depsCell} |`;
  });

  return [
    '# `atlas-chat` Swarm Coordination Board',
    '',
    'Multiple independent Gemini sessions coordinate through this file.',
    'Rule: **One task per session. Never edit files inside another `CLAIMED` task\'s Owned Paths.**',
    '',
    '## Active Task Queue',
    '',
    '| ID | Task | Status | Owner Session | Branch | Owned Paths | Depends On |',
    '| :--- | :--- | :--- | :--- | :--- | :--- | :--- |',
    ...rows,
  ].join('\n');
}

function normalizePath(p: string): string {
  return p.trim().replace(/^\/+/, '').replace(/\/+$/, '');
}

export function pathsOverlap(pathA: string, pathB: string): boolean {
  const a = normalizePath(pathA);
  const b = normalizePath(pathB);
  if (!a || !b) return false;
  if (a === b) return true;

  const baseA = a.replace(/\/\*+$/, '');
  const baseB = b.replace(/\/\*+$/, '');

  return (
    a.startsWith(`${baseB}/`) ||
    b.startsWith(`${baseA}/`) ||
    (a.endsWith('*') && b.startsWith(baseA)) ||
    (b.endsWith('*') && a.startsWith(baseB))
  );
}

export function detectPathConflicts(tasks: BoardTask[]): PathConflict[] {
  const active = tasks.filter((task) => task.status === 'CLAIMED');
  const conflicts: PathConflict[] = [];

  for (let i = 0; i < active.length; i++) {
    for (let j = i + 1; j < active.length; j++) {
      const a = active[i];
      const b = active[j];
      for (const pa of a.ownedPaths) {
        for (const pb of b.ownedPaths) {
          if (pathsOverlap(pa, pb)) {
            conflicts.push({
              path: pa === pb ? pa : `${pa} <-> ${pb}`,
              taskIds: [a.id, b.id],
              sessions: [a.ownerSession, b.ownerSession],
            });
          }
        }
      }
    }
  }

  return conflicts;
}

export function buildSessionHandoffPrompt(
  task: BoardTask,
  allTasks: BoardTask[],
  repoName = 'atlas-chat'
): string {
  const lockedByOthers = allTasks
    .filter((item) => item.id !== task.id && item.status === 'CLAIMED')
    .flatMap((item) => item.ownedPaths.map((p) => `${p} (${item.id} / ${item.ownerSession})`));

  const lockSection =
    lockedByOthers.length > 0
      ? lockedByOthers.map((entry) => `- ${entry}`).join('\n')
      : '- None currently claimed by other sessions.';

  const ownedSection =
    task.ownedPaths.length > 0 ? task.ownedPaths.join(', ') : 'Declare owned paths before editing';

  const depsSection = task.dependsOn.length > 0 ? task.dependsOn.join(', ') : 'None';

  return [
    `/sync claim ${task.id} --strict`,
    '',
    `Repo: ${repoName}`,
    `Task: ${task.id} — ${task.title}`,
    `Branch: ${task.branch || `swarm/${task.id.toLowerCase()}`}`,
    `Owned Paths (you may edit ONLY these): ${ownedSection}`,
    `Upstream Dependencies: ${depsSection}`,
    '',
    'Locked by other active Gemini sessions (DO NOT EDIT):',
    lockSection,
    '',
    'Instructions:',
    '1. Read AGENTS.md, /skills/sync.md, /swarm/BOARD.md, and /swarm/HANDOFFS.md first.',
    `2. Execute /swarm for ${task.id} strictly within your Owned Paths.`,
    '3. Run build, lint, and unit tests before marking the task IN_REVIEW.',
    '4. Append your contract & verification summary to /swarm/HANDOFFS.md when finished.',
  ].join('\n');
}

export function validateNewBoardTask(
  draft: NewBoardTaskDraft,
  existingIds: string[]
): { valid: boolean; errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  const cleanId = draft.id.trim().toUpperCase();

  if (!cleanId) {
    errors.id = 'Enter a task ID (e.g., T-107).';
  } else if (existingIds.map((id) => id.toUpperCase()).includes(cleanId)) {
    errors.id = `Task ${cleanId} already exists on the board.`;
  }

  if (!draft.title.trim()) {
    errors.title = 'Enter a short task description.';
  }

  const paths = draft.ownedPathsText
    .split(',')
    .map((p) => p.trim())
    .filter(Boolean);
  if (paths.length === 0) {
    errors.ownedPaths = 'Specify at least one owned file or folder path to prevent edit conflicts.';
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
  };
}
