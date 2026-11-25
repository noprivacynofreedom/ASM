import React, { useMemo, useState } from 'react';
import {
  CheckCircle2,
  Database,
  Edit3,
  Plus,
  Shield,
  Trash2,
  Trophy,
  UserCheck,
  UserX,
  Users,
} from 'lucide-react';
import type {
  Challenge,
  ChallengeCategory,
  ChallengeDifficulty,
  UserProfile,
  UserProgress,
  UserRole,
} from '../types';
import { sha256Hex } from '../utils/ctfUtils';

interface Props {
  currentUser: UserProfile;
  challenges: Challenge[];
  firestoreChallengeIds: Set<string>;
  allUsers: UserProfile[];
  allSolvedProgress: UserProgress[];
  onSaveChallenge: (
    challenge: Omit<Challenge, 'createdAt' | 'updatedAt' | 'authorUid' | 'stackPreset' | 'sampleFlag'>,
    isUpdate: boolean
  ) => Promise<void>;
  onDeleteChallenge: (challengeId: string) => Promise<void>;
  onSeedNightmareModules: () => Promise<void>;
  onUpdateUserRole: (targetUser: UserProfile, nextRole: UserRole) => Promise<void>;
  onToggleUserStatus: (targetUser: UserProfile) => Promise<void>;
}

const EMPTY_FORM = {
  id: '',
  moduleNum: '11',
  moduleName: 'Custom Lab Module',
  title: '',
  category: 'Stack' as ChallengeCategory,
  difficulty: 'Intermediate' as ChallengeDifficulty,
  arch: 'x86-64',
  points: 200,
  summary: '',
  objective: '',
  zipPath: 'Nightmare/custom_lab/target.bin',
  flagPlain: '',
  existingFlagHash: '',
  flagHint: 'atlas{...}',
  published: true,
  nx: 'Enabled',
  pie: 'Enabled',
  canary: 'Enabled',
  relro: 'Full RELRO',
  exploitTemplate: `#!/usr/bin/env python3\n"""Atlas CTF Analysis Template"""\nprint("Inspect binary mitigations and symbol offsets.")\n`,
};

export function AdminOrganizerView({
  currentUser,
  challenges,
  firestoreChallengeIds,
  allUsers,
  allSolvedProgress,
  onSaveChallenge,
  onDeleteChallenge,
  onSeedNightmareModules,
  onUpdateUserRole,
  onToggleUserStatus,
}: Props) {
  const isAdmin = currentUser.role === 'admin';
  const isOrganizerOrAdmin = currentUser.role === 'admin' || currentUser.role === 'organizer';

  const [tab, setTab] = useState<'challenges' | 'users' | 'leaderboard'>(
    isOrganizerOrAdmin ? 'challenges' : 'leaderboard'
  );
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const leaderboard = useMemo(() => {
    const scoreMap = new Map<string, { handle: string; solves: number; points: number }>();
    for (const p of allSolvedProgress) {
      if (p.status !== 'solved') continue;
      const cur = scoreMap.get(p.uid) || { handle: p.handle, solves: 0, points: 0 };
      cur.solves += 1;
      cur.points += p.pointsEarned;
      cur.handle = p.handle;
      scoreMap.set(p.uid, cur);
    }
    return Array.from(scoreMap.entries())
      .map(([uid, data]) => ({ uid, ...data }))
      .sort((a, b) => b.points - a.points || b.solves - a.solves);
  }, [allSolvedProgress]);

  const startEdit = (c: Challenge) => {
    setEditingId(c.id);
    setForm({
      id: c.id,
      moduleNum: c.moduleNum,
      moduleName: c.moduleName,
      title: c.title,
      category: c.category,
      difficulty: c.difficulty,
      arch: c.arch,
      points: c.points,
      summary: c.summary,
      objective: c.objective,
      zipPath: c.zipPath,
      flagPlain: '',
      existingFlagHash: c.flagHash,
      flagHint: c.flagHint,
      published: c.published,
      nx: c.mitigations.nx,
      pie: c.mitigations.pie,
      canary: c.mitigations.canary,
      relro: c.mitigations.relro,
      exploitTemplate: c.exploitTemplate,
    });
    setFeedback(null);
  };

  const resetForm = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
  };

  const handleSubmitChallenge = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setFeedback(null);
    try {
      const slug = (editingId || form.id || form.title)
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 64);

      if (slug.length < 2) {
        setFeedback('Challenge ID must be at least 2 alphanumeric/hyphen characters.');
        return;
      }

      let flagHash = form.existingFlagHash;
      if (form.flagPlain.trim()) {
        flagHash = await sha256Hex(form.flagPlain.trim());
      }
      if (!/^[a-f0-9]{64}$/.test(flagHash)) {
        setFeedback('Provide a flag value so Atlas can compute a valid SHA-256 flag digest.');
        return;
      }

      const isExistingInFirestore = editingId !== null && firestoreChallengeIds.has(editingId);

      await onSaveChallenge(
        {
          id: slug,
          moduleNum: form.moduleNum.trim().slice(0, 12) || '11',
          moduleName: form.moduleName.trim().slice(0, 100) || 'Custom Module',
          title: form.title.trim().slice(0, 120),
          category: form.category,
          difficulty: form.difficulty,
          arch: form.arch.trim().slice(0, 32) || 'x86-64',
          points: Math.max(10, Math.min(2000, Number(form.points) || 100)),
          summary: form.summary.trim().slice(0, 2000),
          objective: form.objective.trim().slice(0, 1000),
          zipPath: form.zipPath.trim().slice(0, 256) || 'Nightmare/custom/lab.bin',
          flagHash,
          flagHint: form.flagHint.trim().slice(0, 160) || 'atlas{...}',
          published: form.published,
          mitigations: {
            nx: form.nx.trim().slice(0, 32) || 'Enabled',
            pie: form.pie.trim().slice(0, 32) || 'Enabled',
            canary: form.canary.trim().slice(0, 32) || 'Enabled',
            relro: form.relro.trim().slice(0, 32) || 'Full RELRO',
          },
          exploitTemplate: form.exploitTemplate.trim().slice(0, 8000) || '# Analysis notes',
        },
        isExistingInFirestore
      );

      setFeedback(
        isExistingInFirestore
          ? `Updated challenge "${slug}" in Firestore.`
          : `Published challenge "${slug}" to Firestore.`
      );
      resetForm();
    } finally {
      setSaving(false);
    }
  };

  const handleSeed = async () => {
    setSeeding(true);
    setFeedback(null);
    try {
      await onSeedNightmareModules();
      setFeedback('Synchronized built-in Nightmare syllabus modules into Firestore.');
    } finally {
      setSeeding(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Sub-navigation Tabs */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 dark:border-slate-800 pb-4">
        <div>
          <h2 className="text-lg font-bold font-display text-slate-900 dark:text-slate-100">
            {isAdmin
              ? 'Administration & Challenge Studio'
              : isOrganizerOrAdmin
              ? 'Organizer Challenge Studio'
              : 'Competition Scoreboard'}
          </h2>
          <p className="text-xs text-slate-500">
            Active Role: <span className="font-mono font-medium text-slate-900 dark:text-slate-200">{currentUser.role}</span>
            {' · '}
            {isAdmin
              ? 'Full permissions for challenges, user roles, and moderation'
              : isOrganizerOrAdmin
              ? 'Author, edit, and publish challenges'
              : 'View verified competition standings'}
          </p>
        </div>

        <div className="flex items-center gap-1 p-1 rounded-md bg-slate-100 dark:bg-[#111827] border border-slate-200 dark:border-slate-800">
          {isOrganizerOrAdmin && (
            <button
              type="button"
              onClick={() => setTab('challenges')}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded cursor-pointer whitespace-nowrap ${
                tab === 'challenges'
                  ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                  : 'text-slate-600 dark:text-slate-400'
              }`}
            >
              <Shield className="w-3.5 h-3.5" />
              Challenges
            </button>
          )}
          {isAdmin && (
            <button
              type="button"
              onClick={() => setTab('users')}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded cursor-pointer whitespace-nowrap ${
                tab === 'users'
                  ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                  : 'text-slate-600 dark:text-slate-400'
              }`}
            >
              <Users className="w-3.5 h-3.5" />
              Users & Roles ({allUsers.length})
            </button>
          )}
          <button
            type="button"
            onClick={() => setTab('leaderboard')}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded cursor-pointer whitespace-nowrap ${
              tab === 'leaderboard'
                ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                : 'text-slate-600 dark:text-slate-400'
            }`}
          >
            <Trophy className="w-3.5 h-3.5" />
            Leaderboard
          </button>
        </div>
      </div>

      {feedback && (
        <div className="p-3.5 rounded-md border border-emerald-300 dark:border-emerald-900/60 bg-emerald-50 dark:bg-emerald-950/30 text-xs text-emerald-700 dark:text-emerald-300 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{feedback}</span>
        </div>
      )}

      {/* TAB 1: Challenge Studio (Organizer & Admin) */}
      {tab === 'challenges' && isOrganizerOrAdmin && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Existing Challenges Table */}
          <div className="lg:col-span-6 border border-slate-200 dark:border-slate-800 rounded-lg bg-white dark:bg-[#111827] overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
                Managed Challenges ({challenges.length})
              </h3>
              <button
                type="button"
                disabled={seeding}
                onClick={() => void handleSeed()}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer whitespace-nowrap"
              >
                <Database className="w-3.5 h-3.5" />
                {seeding ? 'Syncing...' : 'Sync Nightmare Seeds'}
              </button>
            </div>

            <div className="divide-y divide-slate-100 dark:divide-slate-800/70 max-h-[620px] overflow-y-auto">
              {challenges.map((c) => {
                const inCloud = firestoreChallengeIds.has(c.id);
                return (
                  <div
                    key={c.id}
                    className="px-4 py-3 flex items-center justify-between gap-3 text-xs hover:bg-slate-50 dark:hover:bg-slate-800/40"
                  >
                    <div className="min-w-0">
                      <p className="font-medium text-slate-900 dark:text-slate-100 truncate">
                        {c.moduleNum}. {c.title}
                      </p>
                      <p className="text-slate-500 mt-0.5 font-mono truncate">
                        {c.category} · {c.points} pts · {c.published ? 'Published' : 'Draft'} ·{' '}
                        {inCloud ? 'Cloud DB' : 'Local Seed'}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        type="button"
                        onClick={() => startEdit(c)}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer"
                      >
                        <Edit3 className="w-3 h-3" />
                        Edit
                      </button>
                      {isAdmin && inCloud && (
                        <button
                          type="button"
                          onClick={() => void onDeleteChallenge(c.id)}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded border border-red-300 dark:border-red-900/60 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 cursor-pointer"
                        >
                          <Trash2 className="w-3 h-3" />
                          Delete
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Author / Edit Challenge Form */}
          <form
            onSubmit={handleSubmitChallenge}
            className="lg:col-span-6 border border-slate-200 dark:border-slate-800 rounded-lg p-5 bg-white dark:bg-[#111827] space-y-4"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
                {editingId ? `Edit Challenge: ${editingId}` : 'Create New Challenge'}
              </h3>
              {editingId && (
                <button
                  type="button"
                  onClick={resetForm}
                  className="text-xs text-slate-500 hover:text-slate-900 dark:hover:text-slate-200 cursor-pointer"
                >
                  Cancel Edit
                </button>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className="block text-xs text-slate-500 mb-1">Module #</label>
                <input
                  type="text"
                  required
                  value={form.moduleNum}
                  onChange={(e) => setForm({ ...form, moduleNum: e.target.value })}
                  className="w-full px-2.5 py-1.5 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="block text-xs text-slate-500 mb-1">Slug ID (a-z, 0-9, -)</label>
                <input
                  type="text"
                  required
                  disabled={Boolean(editingId)}
                  value={form.id}
                  onChange={(e) => setForm({ ...form, id: e.target.value })}
                  placeholder="nm-11-canary-bypass-lab"
                  className="w-full px-2.5 py-1.5 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700 disabled:opacity-60"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-500 mb-1">Challenge Title</label>
                <input
                  type="text"
                  required
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="ELF Dynamic Relocation Lab"
                  className="w-full px-2.5 py-1.5 text-xs rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">Module Name</label>
                <input
                  type="text"
                  required
                  value={form.moduleName}
                  onChange={(e) => setForm({ ...form, moduleName: e.target.value })}
                  className="w-full px-2.5 py-1.5 text-xs rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div>
                <label className="block text-xs text-slate-500 mb-1">Category</label>
                <select
                  value={form.category}
                  onChange={(e) =>
                    setForm({ ...form, category: e.target.value as ChallengeCategory })
                  }
                  className="w-full px-2 py-1.5 text-xs rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700"
                >
                  {['Reversing', 'Stack', 'ROP', 'Format', 'Heap', 'Mitigations'].map((cat) => (
                    <option key={cat} value={cat}>
                      {cat}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">Difficulty</label>
                <select
                  value={form.difficulty}
                  onChange={(e) =>
                    setForm({ ...form, difficulty: e.target.value as ChallengeDifficulty })
                  }
                  className="w-full px-2 py-1.5 text-xs rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700"
                >
                  {['Beginner', 'Intermediate', 'Advanced'].map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">Arch</label>
                <input
                  type="text"
                  value={form.arch}
                  onChange={(e) => setForm({ ...form, arch: e.target.value })}
                  className="w-full px-2.5 py-1.5 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">Points</label>
                <input
                  type="number"
                  min={10}
                  max={2000}
                  value={form.points}
                  onChange={(e) => setForm({ ...form, points: Number(e.target.value) })}
                  className="w-full px-2.5 py-1.5 text-xs font-mono tabular-nums rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs text-slate-500 mb-1">Summary</label>
              <textarea
                rows={2}
                required
                value={form.summary}
                onChange={(e) => setForm({ ...form, summary: e.target.value })}
                className="w-full p-2.5 text-xs rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-500 mb-1">Lab Objective</label>
              <input
                type="text"
                required
                value={form.objective}
                onChange={(e) => setForm({ ...form, objective: e.target.value })}
                className="w-full px-2.5 py-1.5 text-xs rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-500 mb-1">
                  Plaintext Flag (auto-hashed via SHA-256)
                </label>
                <input
                  type="text"
                  required={!editingId}
                  value={form.flagPlain}
                  onChange={(e) => setForm({ ...form, flagPlain: e.target.value })}
                  placeholder={editingId ? 'Leave blank to keep existing hash' : 'atlas{...}'}
                  className="w-full px-2.5 py-1.5 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">Nightmare.zip Path</label>
                <input
                  type="text"
                  required
                  value={form.zipPath}
                  onChange={(e) => setForm({ ...form, zipPath: e.target.value })}
                  className="w-full px-2.5 py-1.5 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700"
                />
              </div>
            </div>

            <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.published}
                onChange={(e) => setForm({ ...form, published: e.target.checked })}
                className="rounded border-slate-400 text-amber-500"
              />
              Published (visible to Players immediately; uncheck to save as Organizer Draft)
            </label>

            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-md bg-amber-500 text-slate-950 hover:bg-amber-400 disabled:opacity-50 cursor-pointer whitespace-nowrap"
            >
              <Plus className="w-3.5 h-3.5" />
              {saving ? 'Saving...' : editingId ? 'Save Challenge Changes' : 'Publish Challenge'}
            </button>
          </form>
        </div>
      )}

      {/* TAB 2: User & Role Management (Admin Only) */}
      {tab === 'users' && isAdmin && (
        <div className="border border-slate-200 dark:border-slate-800 rounded-lg bg-white dark:bg-[#111827] overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
            <h3 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
              Registered Operators & Role Assignments
            </h3>
            <span className="text-xs text-slate-500">
              Role grants update /admins and /organizers RBAC registries atomically
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 dark:bg-[#0B1120] text-slate-500 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="text-left px-4 py-2.5 font-medium">Operator</th>
                  <th className="text-left px-4 py-2.5 font-medium">Team</th>
                  <th className="text-left px-4 py-2.5 font-medium">Role</th>
                  <th className="text-left px-4 py-2.5 font-medium">Request</th>
                  <th className="text-left px-4 py-2.5 font-medium">Status</th>
                  <th className="text-right px-4 py-2.5 font-medium">Admin Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
                {allUsers.map((u) => {
                  const isSelf = u.uid === currentUser.uid;
                  return (
                    <tr key={u.uid} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                      <td className="px-4 py-3">
                        <p className="font-mono font-medium text-slate-900 dark:text-slate-100">
                          @{u.handle} {isSelf ? '(you)' : ''}
                        </p>
                        <p className="text-slate-500">{u.displayName}</p>
                      </td>
                      <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                        {u.teamName || '—'}
                      </td>
                      <td className="px-4 py-3">
                        <select
                          disabled={isSelf}
                          value={u.role}
                          onChange={(e) => void onUpdateUserRole(u, e.target.value as UserRole)}
                          className="px-2 py-1 text-xs font-mono rounded bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700 disabled:opacity-60"
                        >
                          <option value="player">player</option>
                          <option value="organizer">organizer</option>
                          <option value="admin">admin</option>
                        </select>
                      </td>
                      <td className="px-4 py-3 font-mono">
                        {u.requestedRole === 'organizer' && u.role === 'player' ? (
                          <button
                            type="button"
                            onClick={() => void onUpdateUserRole(u, 'organizer')}
                            className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400 hover:underline cursor-pointer"
                          >
                            <UserCheck className="w-3.5 h-3.5" />
                            Approve Organizer
                          </button>
                        ) : (
                          <span className="text-slate-500">None</span>
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono">
                        <span
                          className={
                            u.status === 'active'
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : 'text-red-600 dark:text-red-400'
                          }
                        >
                          {u.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        {!isSelf && (
                          <button
                            type="button"
                            onClick={() => void onToggleUserStatus(u)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer"
                          >
                            <UserX className="w-3 h-3" />
                            {u.status === 'active' ? 'Suspend' : 'Reactivate'}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 3: Scoreboard / Leaderboard */}
      {tab === 'leaderboard' && (
        <div className="border border-slate-200 dark:border-slate-800 rounded-lg bg-white dark:bg-[#111827] overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
            <h3 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
              Verified Solve Standings
            </h3>
            <span className="text-xs font-mono tabular-nums text-slate-500">
              {leaderboard.length} ranked operators
            </span>
          </div>

          <table className="w-full text-xs">
            <thead className="bg-slate-50 dark:bg-[#0B1120] text-slate-500 border-b border-slate-200 dark:border-slate-800">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium w-16">Rank</th>
                <th className="text-left px-4 py-2.5 font-medium">Handle</th>
                <th className="text-right px-4 py-2.5 font-medium">Solves</th>
                <th className="text-right px-4 py-2.5 font-medium">Points</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
              {leaderboard.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-slate-500">
                    No verified flags recorded yet. Solve a Nightmare lab to claim rank #1.
                  </td>
                </tr>
              ) : (
                leaderboard.map((row, idx) => (
                  <tr key={row.uid} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                    <td className="px-4 py-3 font-mono tabular-nums text-slate-500">#{idx + 1}</td>
                    <td className="px-4 py-3 font-mono font-medium text-slate-900 dark:text-slate-100">
                      @{row.handle}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-slate-600 dark:text-slate-300">
                      {row.solves}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums font-semibold text-amber-600 dark:text-amber-400">
                      {row.points}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
