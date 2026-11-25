import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {
  composeCommand,
  filterSkills,
  generateSkillMarkdown,
  parseSkillMarkdown,
  slugifySkillName,
  validateCustomSkillDraft,
} from './skillParser';
import {
  buildSessionHandoffPrompt,
  detectPathConflicts,
  parseBoardMarkdown,
  pathsOverlap,
  serializeBoardMarkdown,
  validateNewBoardTask,
} from './boardParser';

test('parseSkillMarkdown parses actual /skills/swarm.md frontmatter and 5 phases', () => {
  const raw = fs.readFileSync(path.resolve('skills/swarm.md'), 'utf8');
  const spec = parseSkillMarkdown('/skills/swarm.md', raw);

  assert.equal(spec.command, '/swarm');
  assert.equal(spec.name, 'swarm');
  assert.equal(spec.category, 'Delivery');
  assert.equal(spec.phases.length, 5);
  assert.equal(spec.phases[0].role, 'Architect');
  assert.equal(spec.phases[4].role, 'QA Engineer');
  assert.ok(spec.phases[0].deliverables.length >= 3);
  assert.ok(spec.guardrails.length >= 2);
});

test('parseSkillMarkdown parses /skills/sync.md multi-session coordination skill', () => {
  const raw = fs.readFileSync(path.resolve('skills/sync.md'), 'utf8');
  const spec = parseSkillMarkdown('/skills/sync.md', raw);

  assert.equal(spec.command, '/sync');
  assert.equal(spec.category, 'Coordination');
  assert.equal(spec.phases.length, 4);
  assert.equal(spec.phases[0].role, 'Session Coordinator');
});

test('composeCommand formats slash command, trimmed task, and deduplicated flags', () => {
  assert.equal(
    composeCommand('/swarm', '  Add message   reactions  ', ['--strict', '--ui-first', '--strict']),
    '/swarm Add message reactions --strict --ui-first'
  );
  assert.equal(composeCommand('review', '', ['--plan-only']), '/review --plan-only');
});

test('custom skill draft validation and markdown round-trip parsing', () => {
  const invalid = validateCustomSkillDraft(
    {
      name: 'swarm',
      title: '',
      category: 'Quality',
      summary: 'short',
      flags: [],
      phases: [{ title: '', role: '', objective: '', deliverablesText: '', exitGate: '' }],
      guardrailsText: '',
    },
    ['swarm', 'sync']
  );

  assert.equal(invalid.valid, false);
  assert.ok(invalid.errors.name);
  assert.ok(invalid.errors.title);
  assert.ok(invalid.errors.summary);
  assert.ok(invalid.errors.phases);

  const validDraft = {
    name: '/Perf Audit!',
    title: 'Latency & Render Profiler',
    category: 'Performance',
    summary: 'Profiles atlas-chat message list rendering and socket throughput regressions.',
    flags: ['--strict', '--no-deps'],
    phases: [
      {
        title: 'Baseline Capture',
        role: 'Performance Engineer',
        objective: 'Measure frame drops and memory footprint on 500-message threads.',
        deliverablesText: 'Profiler trace\nFrame budget table',
        exitGate: 'Baseline numbers recorded before edits.',
      },
    ],
    guardrailsText: 'Never sacrifice accessibility for micro-optimizations.',
  };

  const valid = validateCustomSkillDraft(validDraft, ['swarm']);
  assert.equal(valid.valid, true);
  assert.equal(slugifySkillName(validDraft.name), 'perf-audit');

  const md = generateSkillMarkdown(validDraft);
  const parsed = parseSkillMarkdown('/skills/perf-audit.md', md, { isCustom: true });
  assert.equal(parsed.command, '/perf-audit');
  assert.equal(parsed.phases.length, 1);
  assert.equal(parsed.phases[0].deliverables.length, 2);
});

test('filterSkills matches command, roles, and category accurately', () => {
  const swarm = parseSkillMarkdown('/skills/swarm.md', fs.readFileSync(path.resolve('skills/swarm.md'), 'utf8'));
  const sync = parseSkillMarkdown('/skills/sync.md', fs.readFileSync(path.resolve('skills/sync.md'), 'utf8'));

  assert.equal(filterSkills([swarm, sync], 'coordinator', 'All').length, 1);
  assert.equal(filterSkills([swarm, sync], '', 'Delivery').length, 1);
  assert.equal(filterSkills([swarm, sync], 'zzz-no-match', 'All').length, 0);
});

test('parseBoardMarkdown parses /swarm/BOARD.md and round-trips cleanly', () => {
  const raw = fs.readFileSync(path.resolve('swarm/BOARD.md'), 'utf8');
  const tasks = parseBoardMarkdown(raw);

  assert.equal(tasks.length, 6);
  assert.equal(tasks[0].id, 'T-101');
  assert.equal(tasks[0].status, 'DONE');
  assert.equal(tasks[1].status, 'CLAIMED');
  assert.deepEqual(tasks[1].ownedPaths, ['src/lib/sendQueue.ts', 'src/lib/sendQueue.test.ts']);

  const serialized = serializeBoardMarkdown(tasks);
  const reparsed = parseBoardMarkdown(serialized);
  assert.deepEqual(reparsed, tasks);
});

test('detectPathConflicts detects overlapping paths on CLAIMED tasks only', () => {
  assert.equal(pathsOverlap('src/lib/sendQueue.ts', 'src/lib/*'), true);
  assert.equal(pathsOverlap('src/lib/sendQueue.ts', 'src/components/Chat.tsx'), false);

  const conflicts = detectPathConflicts([
    {
      id: 'T-201',
      title: 'Session A',
      status: 'CLAIMED',
      ownerSession: 'session-a',
      branch: 'swarm/a',
      ownedPaths: ['src/lib/sendQueue.ts'],
      dependsOn: [],
    },
    {
      id: 'T-202',
      title: 'Session B',
      status: 'CLAIMED',
      ownerSession: 'session-b',
      branch: 'swarm/b',
      ownedPaths: ['src/lib/*'],
      dependsOn: [],
    },
    {
      id: 'T-203',
      title: 'Session C (TODO ignored)',
      status: 'TODO',
      ownerSession: 'unassigned',
      branch: 'swarm/c',
      ownedPaths: ['src/lib/sendQueue.ts'],
      dependsOn: [],
    },
  ]);

  assert.equal(conflicts.length, 1);
  assert.deepEqual(conflicts[0].taskIds, ['T-201', 'T-202']);
});

test('buildSessionHandoffPrompt includes owned paths and active locks from other sessions', () => {
  const tasks = parseBoardMarkdown(fs.readFileSync(path.resolve('swarm/BOARD.md'), 'utf8'));
  const target = tasks.find((t) => t.id === 'T-103')!;
  const prompt = buildSessionHandoffPrompt(target, tasks, 'atlas-chat');

  assert.match(prompt, /^\/sync claim T-103 --strict/);
  assert.match(prompt, /src\/components\/ThreadSidebar\.tsx/);
  assert.match(prompt, /src\/lib\/sendQueue\.ts \(T-102 \/ session-logic-02\)/);
});

test('validateNewBoardTask rejects duplicates and empty owned paths', () => {
  const bad = validateNewBoardTask(
    { id: 'T-101', title: '', branch: '', ownedPathsText: '', dependsOnText: '' },
    ['T-101']
  );
  assert.equal(bad.valid, false);
  assert.ok(bad.errors.id);
  assert.ok(bad.errors.title);
  assert.ok(bad.errors.ownedPaths);
});
