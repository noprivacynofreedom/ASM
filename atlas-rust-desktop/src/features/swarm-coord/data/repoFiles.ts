import agentsMd from '../../../../../AGENTS.md?raw';
import boardMd from '../../../../../swarm/BOARD.md?raw';
import handoffsMd from '../../../../../swarm/HANDOFFS.md?raw';
import { parseSkillMarkdown, type SkillSpec } from '../utils/skillParser';
import { parseBoardMarkdown, type BoardTask } from '../utils/boardParser';

const skillModules = import.meta.glob<string>('../../../../../skills/*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
});

const SKILL_ORDER = ['swarm', 'sync', 'architect', 'review', 'qa', 'debug', 'refactor'];

export interface RepoDoc {
  id: string;
  title: string;
  filePath: string;
  summary: string;
  rawMarkdown: string;
}

export function normalizeRepoSkillPath(filePath: string): string {
  const cleaned = filePath.replace(/\\/g, '/').replace(/^(\.\.\/)+/, '').replace(/^\/+/, '');
  return `/${cleaned}`;
}

export function loadRepoSkills(): SkillSpec[] {
  const parsed = Object.entries(skillModules).map(([filePath, raw]) =>
    parseSkillMarkdown(normalizeRepoSkillPath(filePath), raw)
  );

  return parsed.sort((a, b) => {
    const idxA = SKILL_ORDER.indexOf(a.name);
    const idxB = SKILL_ORDER.indexOf(b.name);
    if (idxA !== -1 && idxB !== -1) return idxA - idxB;
    if (idxA !== -1) return -1;
    if (idxB !== -1) return 1;
    return a.name.localeCompare(b.name);
  });
}

export function loadRepoDocs(): RepoDoc[] {
  return [
    {
      id: 'agents',
      title: 'AGENTS.md',
      filePath: '/AGENTS.md',
      summary: 'Root command registry, modifier flags, and multi-session coordination rules for atlas-chat.',
      rawMarkdown: agentsMd.trim(),
    },
    {
      id: 'handoffs',
      title: 'swarm/HANDOFFS.md',
      filePath: '/swarm/HANDOFFS.md',
      summary: 'Shared contract notes and verification handoffs passed between independent Gemini sessions.',
      rawMarkdown: handoffsMd.trim(),
    },
    {
      id: 'board-raw',
      title: 'swarm/BOARD.md',
      filePath: '/swarm/BOARD.md',
      summary: 'Raw task claim table and file-ownership locks checked into Git.',
      rawMarkdown: boardMd.trim(),
    },
  ];
}

export function loadInitialBoardTasks(): BoardTask[] {
  return parseBoardMarkdown(boardMd);
}
