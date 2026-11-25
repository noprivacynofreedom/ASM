export interface SkillPhase {
  index: number;
  title: string;
  role: string;
  objective: string;
  deliverables: string[];
  exitGate: string;
}

export interface SkillSpec {
  id: string;
  filePath: string;
  name: string;
  command: string;
  title: string;
  category: string;
  summary: string;
  roles: string[];
  flags: string[];
  usage: string;
  phases: SkillPhase[];
  guardrails: string[];
  rawMarkdown: string;
  isCustom?: boolean;
}

export interface CustomSkillPhaseDraft {
  title: string;
  role: string;
  objective: string;
  deliverablesText: string;
  exitGate: string;
}

export interface CustomSkillDraft {
  name: string;
  title: string;
  category: string;
  summary: string;
  flags: string[];
  phases: CustomSkillPhaseDraft[];
  guardrailsText: string;
}

export interface DraftValidationResult {
  valid: boolean;
  errors: Record<string, string>;
}

const KNOWN_FLAGS = ['--strict', '--plan-only', '--ui-first', '--no-deps', '--tests-only'];

export function getGlobalFlags(): string[] {
  return [...KNOWN_FLAGS];
}

export function slugifySkillName(input: string): string {
  return input
    .trim()
    .toLowerCase()
    .replace(/^\/+/, '')
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}

function parseFrontmatter(raw: string): { meta: Record<string, string>; body: string } {
  const normalized = raw.replace(/\r\n/g, '\n');
  const match = normalized.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!match) {
    return { meta: {}, body: normalized };
  }

  const meta: Record<string, string> = {};
  for (const line of match[1].split('\n')) {
    const colonIndex = line.indexOf(':');
    if (colonIndex === -1) continue;
    const key = line.slice(0, colonIndex).trim();
    const value = line.slice(colonIndex + 1).trim();
    if (key) {
      meta[key] = value;
    }
  }

  return { meta, body: match[2].trim() };
}

function splitCsv(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function extractSection(body: string, heading: string): string {
  const lines = body.split('\n');
  const target = `## ${heading}`;
  const startIdx = lines.findIndex((line) => line.trim() === target);
  if (startIdx === -1) return '';

  const collected: string[] = [];
  for (let i = startIdx + 1; i < lines.length; i++) {
    if (/^##\s+/.test(lines[i])) break;
    collected.push(lines[i]);
  }
  return collected.join('\n').trim();
}

function parsePhases(phasesSection: string): SkillPhase[] {
  if (!phasesSection) return [];

  const blocks = phasesSection.split(/^###\s+/m).filter((chunk) => chunk.trim().length > 0);
  const phases: SkillPhase[] = [];

  blocks.forEach((block, idx) => {
    const lines = block.split('\n');
    const headingLine = (lines[0] || '').trim();
    const headingMatch = headingLine.match(/^(\d+)\.\s*(.+)$/);
    const index = headingMatch ? Number.parseInt(headingMatch[1], 10) : idx + 1;
    const title = headingMatch ? headingMatch[2].trim() : headingLine;

    let role = '';
    let objective = '';
    let exitGate = '';
    const deliverables: string[] = [];
    let inDeliverables = false;

    for (let i = 1; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();

      if (trimmed.startsWith('- **Role**:')) {
        role = trimmed.replace('- **Role**:', '').trim();
        inDeliverables = false;
      } else if (trimmed.startsWith('- **Objective**:')) {
        objective = trimmed.replace('- **Objective**:', '').trim();
        inDeliverables = false;
      } else if (trimmed.startsWith('- **Deliverables**:')) {
        inDeliverables = true;
      } else if (trimmed.startsWith('- **Exit Gate**:')) {
        exitGate = trimmed.replace('- **Exit Gate**:', '').trim();
        inDeliverables = false;
      } else if (inDeliverables && trimmed.startsWith('- ')) {
        deliverables.push(trimmed.slice(2).trim());
      }
    }

    phases.push({
      index,
      title,
      role: role || 'Engineer',
      objective,
      deliverables,
      exitGate,
    });
  });

  return phases;
}

function parseBulletList(section: string): string[] {
  if (!section) return [];
  return section
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('- '))
    .map((line) => line.slice(2).trim());
}

function parseUsage(usageSection: string, fallbackCommand: string): string {
  const codeMatch = usageSection.match(/```[^\n]*\n([\s\S]*?)```/);
  if (codeMatch) {
    return codeMatch[1].trim();
  }
  return `${fallbackCommand} <task description>`;
}

export function parseSkillMarkdown(
  filePath: string,
  raw: string,
  options?: { isCustom?: boolean }
): SkillSpec {
  const { meta, body } = parseFrontmatter(raw);
  const fileBase = filePath.split('/').pop()?.replace(/\.md$/i, '') || 'skill';
  const name = slugifySkillName(meta.name || fileBase) || 'skill';
  const command = meta.command?.startsWith('/') ? meta.command.trim() : `/${name}`;
  const title = meta.title || name;
  const category = meta.category || 'Workflow';
  const summary = meta.summary || '';
  const roles = splitCsv(meta.roles);
  const flags = splitCsv(meta.flags);

  const usageSection = extractSection(body, 'Usage');
  const phasesSection = extractSection(body, 'Phases');
  const guardrailsSection = extractSection(body, 'Guardrails');

  const phases = parsePhases(phasesSection);
  const guardrails = parseBulletList(guardrailsSection);
  const usage = parseUsage(usageSection, command);

  return {
    id: name,
    filePath,
    name,
    command,
    title,
    category,
    summary,
    roles: roles.length > 0 ? roles : Array.from(new Set(phases.map((p) => p.role))),
    flags,
    usage,
    phases,
    guardrails,
    rawMarkdown: raw.replace(/\r\n/g, '\n').trim(),
    isCustom: Boolean(options?.isCustom),
  };
}

export function composeCommand(command: string, task: string, flags: string[]): string {
  const cleanCmd = command.trim().startsWith('/') ? command.trim() : `/${command.trim()}`;
  const cleanTask = task.trim().replace(/\s+/g, ' ');
  const uniqueFlags = Array.from(new Set(flags.map((flag) => flag.trim()).filter(Boolean)));

  const parts = [cleanCmd];
  if (cleanTask) {
    parts.push(cleanTask);
  }
  if (uniqueFlags.length > 0) {
    parts.push(...uniqueFlags);
  }
  return parts.join(' ');
}

export function filterSkills(skills: SkillSpec[], query: string, category: string): SkillSpec[] {
  const normalizedQuery = query.trim().toLowerCase();
  const normalizedCategory = category.trim().toLowerCase();

  return skills.filter((skill) => {
    const matchesCategory =
      !normalizedCategory ||
      normalizedCategory === 'all' ||
      skill.category.toLowerCase() === normalizedCategory;

    if (!matchesCategory) return false;
    if (!normalizedQuery) return true;

    const haystack = [
      skill.command,
      skill.name,
      skill.title,
      skill.summary,
      skill.category,
      ...skill.roles,
      ...skill.phases.map((p) => `${p.title} ${p.role} ${p.objective}`),
    ]
      .join(' ')
      .toLowerCase();

    return haystack.includes(normalizedQuery);
  });
}

export function validateCustomSkillDraft(
  draft: CustomSkillDraft,
  existingIds: string[]
): DraftValidationResult {
  const errors: Record<string, string> = {};
  const slug = slugifySkillName(draft.name);

  if (!slug) {
    errors.name = 'Enter a command slug (letters, numbers, or hyphens).';
  } else if (existingIds.includes(slug)) {
    errors.name = `Command /${slug} already exists in this workspace.`;
  }

  if (!draft.title.trim()) {
    errors.title = 'Enter a concise workflow title.';
  }

  if (!draft.summary.trim() || draft.summary.trim().length < 12) {
    errors.summary = 'Describe when to use this workflow (at least 12 characters).';
  }

  const validPhases = draft.phases.filter(
    (phase) => phase.title.trim() && phase.role.trim() && phase.objective.trim()
  );
  if (validPhases.length === 0) {
    errors.phases = 'Add at least one phase with a title, role, and objective.';
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
  };
}

export function generateSkillMarkdown(draft: CustomSkillDraft): string {
  const slug = slugifySkillName(draft.name) || 'custom';
  const command = `/${slug}`;
  const cleanPhases = draft.phases.filter(
    (phase) => phase.title.trim() && phase.role.trim() && phase.objective.trim()
  );
  const roles = Array.from(new Set(cleanPhases.map((phase) => phase.role.trim())));
  const flags = draft.flags.length > 0 ? draft.flags : ['--strict', '--plan-only'];
  const usageFlags = flags.map((flag) => `[${flag}]`).join(' ');

  const phaseBlocks = cleanPhases.map((phase, idx) => {
    const deliverables = phase.deliverablesText
      .split('\n')
      .map((line) => line.trim().replace(/^-\s*/, ''))
      .filter(Boolean);
    const deliverableLines =
      deliverables.length > 0
        ? deliverables.map((item) => `  - ${item}`).join('\n')
        : '  - Document phase output and verified changes';

    return [
      `### ${idx + 1}. ${phase.title.trim()}`,
      `- **Role**: ${phase.role.trim()}`,
      `- **Objective**: ${phase.objective.trim()}`,
      `- **Deliverables**:`,
      deliverableLines,
      `- **Exit Gate**: ${phase.exitGate.trim() || 'Phase deliverables verified with zero regressions.'}`,
    ].join('\n');
  });

  const guardrails = draft.guardrailsText
    .split('\n')
    .map((line) => line.trim().replace(/^-\s*/, ''))
    .filter(Boolean);
  const guardrailLines =
    guardrails.length > 0
      ? guardrails.map((item) => `- ${item}`).join('\n')
      : '- Respect file ownership boundaries in /swarm/BOARD.md.';

  return [
    '---',
    `name: ${slug}`,
    `command: ${command}`,
    `title: ${draft.title.trim()}`,
    `category: ${draft.category.trim() || 'Custom'}`,
    `summary: ${draft.summary.trim()}`,
    `roles: ${roles.join(', ')}`,
    `flags: ${flags.join(', ')}`,
    '---',
    '',
    `# ${command} — ${draft.title.trim()}`,
    '',
    draft.summary.trim(),
    '',
    '## Usage',
    '',
    '```text',
    `${command} <scope or goal> ${usageFlags}`.trim(),
    '```',
    '',
    '## Phases',
    '',
    phaseBlocks.join('\n\n'),
    '',
    '## Guardrails',
    '',
    guardrailLines,
  ].join('\n');
}
