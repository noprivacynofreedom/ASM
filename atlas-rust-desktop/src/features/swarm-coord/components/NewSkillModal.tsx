import { useState } from 'react';
import { Plus, Trash2, X } from 'lucide-react';
import {
  generateSkillMarkdown,
  getGlobalFlags,
  parseSkillMarkdown,
  slugifySkillName,
  validateCustomSkillDraft,
  type CustomSkillDraft,
  type SkillSpec,
} from '../utils/skillParser';

interface NewSkillModalProps {
  open: boolean;
  existingIds: string[];
  onClose: () => void;
  onCreateSkill: (skill: SkillSpec) => void;
}

const INITIAL_DRAFT: CustomSkillDraft = {
  name: '',
  title: '',
  category: 'Custom',
  summary: '',
  flags: ['--strict', '--plan-only'],
  phases: [
    {
      title: 'Scope & Analysis',
      role: 'Lead Engineer',
      objective: '',
      deliverablesText: '',
      exitGate: '',
    },
  ],
  guardrailsText: 'Respect file ownership locks in /swarm/BOARD.md.',
};

export function NewSkillModal({
  open,
  existingIds,
  onClose,
  onCreateSkill,
}: NewSkillModalProps) {
  const [draft, setDraft] = useState<CustomSkillDraft>(INITIAL_DRAFT);
  const [errors, setErrors] = useState<Record<string, string>>({});

  if (!open) return null;

  const globalFlags = getGlobalFlags();

  const handleToggleFlag = (flag: string) => {
    setDraft((prev) => ({
      ...prev,
      flags: prev.flags.includes(flag)
        ? prev.flags.filter((item) => item !== flag)
        : [...prev.flags, flag],
    }));
  };

  const handlePhaseChange = (
    idx: number,
    field: keyof CustomSkillDraft['phases'][number],
    value: string
  ) => {
    setDraft((prev) => ({
      ...prev,
      phases: prev.phases.map((phase, i) => (i === idx ? { ...phase, [field]: value } : phase)),
    }));
  };

  const handleAddPhase = () => {
    setDraft((prev) => ({
      ...prev,
      phases: [
        ...prev.phases,
        {
          title: '',
          role: '',
          objective: '',
          deliverablesText: '',
          exitGate: '',
        },
      ],
    }));
  };

  const handleRemovePhase = (idx: number) => {
    setDraft((prev) => ({
      ...prev,
      phases: prev.phases.filter((_, i) => i !== idx),
    }));
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const validation = validateCustomSkillDraft(draft, existingIds);
    if (!validation.valid) {
      setErrors(validation.errors);
      return;
    }

    const slug = slugifySkillName(draft.name);
    const markdown = generateSkillMarkdown(draft);
    const parsed = parseSkillMarkdown(`/skills/${slug}.md`, markdown, { isCustom: true });
    onCreateSkill(parsed);
    setDraft(INITIAL_DRAFT);
    setErrors({});
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="new-skill-modal-title"
    >
      <div
        className="fixed inset-0 bg-black/70"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="relative z-10 w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl border border-[#2A3347] bg-[#111622] shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[#232836] bg-[#111622] px-6 py-4">
          <div>
            <h2 id="new-skill-modal-title" className="text-lg font-semibold text-slate-100">
              Create Workflow Skill
            </h2>
            <p className="text-xs text-slate-400">
              Generates a reusable <span className="font-mono text-slate-300">/skills/&lt;name&gt;.md</span>{' '}
              playbook for atlas-chat.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close modal"
            className="rounded-lg p-2 text-slate-400 hover:bg-[#1B2233] hover:text-slate-100 focus-visible:outline-2 focus-visible:outline-blue-500"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate className="p-6 space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="new-skill-name" className="block text-xs font-medium text-slate-300">
                Slash Command Slug
              </label>
              <input
                id="new-skill-name"
                type="text"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder="perf"
                className="mt-1 w-full rounded-lg border border-[#2A3347] bg-[#0B0F17] px-3 py-2 font-mono text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
              />
              {errors.name && <p className="mt-1 text-xs text-red-400">{errors.name}</p>}
            </div>

            <div>
              <label htmlFor="new-skill-title" className="block text-xs font-medium text-slate-300">
                Workflow Title
              </label>
              <input
                id="new-skill-title"
                type="text"
                value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                placeholder="Performance Audit"
                className="mt-1 w-full rounded-lg border border-[#2A3347] bg-[#0B0F17] px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
              />
              {errors.title && <p className="mt-1 text-xs text-red-400">{errors.title}</p>}
            </div>
          </div>

          <div>
            <label htmlFor="new-skill-summary" className="block text-xs font-medium text-slate-300">
              Summary
            </label>
            <textarea
              id="new-skill-summary"
              rows={2}
              value={draft.summary}
              onChange={(e) => setDraft({ ...draft, summary: e.target.value })}
              placeholder="Profiles chat message list virtualization, bundle size, and socket throughput."
              className="mt-1 w-full rounded-lg border border-[#2A3347] bg-[#0B0F17] px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
            />
            {errors.summary && <p className="mt-1 text-xs text-red-400">{errors.summary}</p>}
          </div>

          <div>
            <span className="block text-xs font-medium text-slate-300 mb-2">Default Flags</span>
            <div className="flex flex-wrap gap-2">
              {globalFlags.map((flag) => {
                const active = draft.flags.includes(flag);
                return (
                  <button
                    key={flag}
                    type="button"
                    aria-pressed={active}
                    onClick={() => handleToggleFlag(flag)}
                    className={`rounded-md border px-2.5 py-1 font-mono text-xs transition-colors ${
                      active
                        ? 'border-blue-500 bg-blue-600/20 text-blue-200'
                        : 'border-[#2A3347] bg-[#141A29] text-slate-300 hover:bg-[#1B2233]'
                    }`}
                  >
                    {flag}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="space-y-3 pt-2 border-t border-[#232836]">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-300">Sequential Phases</span>
              <button
                type="button"
                onClick={handleAddPhase}
                className="inline-flex items-center gap-1 text-xs font-medium text-blue-400 hover:underline"
              >
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                Add Phase
              </button>
            </div>
            {errors.phases && <p className="text-xs text-red-400">{errors.phases}</p>}

            <div className="space-y-4">
              {draft.phases.map((phase, idx) => (
                <div
                  key={idx}
                  className="rounded-lg border border-[#232836] bg-[#0D121E] p-4 space-y-3"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-medium text-slate-400">
                      Phase 0{idx + 1}
                    </span>
                    {draft.phases.length > 1 && (
                      <button
                        type="button"
                        onClick={() => handleRemovePhase(idx)}
                        aria-label={`Remove phase ${idx + 1}`}
                        className="text-slate-400 hover:text-red-400"
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    )}
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label
                        htmlFor={`phase-title-${idx}`}
                        className="block text-xs font-medium text-slate-400"
                      >
                        Phase Title
                      </label>
                      <input
                        id={`phase-title-${idx}`}
                        type="text"
                        value={phase.title}
                        onChange={(e) => handlePhaseChange(idx, 'title', e.target.value)}
                        placeholder="Baseline Profiling"
                        className="mt-1 w-full rounded-md border border-[#2A3347] bg-[#0B0F17] px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label
                        htmlFor={`phase-role-${idx}`}
                        className="block text-xs font-medium text-slate-400"
                      >
                        Role
                      </label>
                      <input
                        id={`phase-role-${idx}`}
                        type="text"
                        value={phase.role}
                        onChange={(e) => handlePhaseChange(idx, 'role', e.target.value)}
                        placeholder="Performance Engineer"
                        className="mt-1 w-full rounded-md border border-[#2A3347] bg-[#0B0F17] px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
                      />
                    </div>
                  </div>

                  <div>
                    <label
                      htmlFor={`phase-objective-${idx}`}
                      className="block text-xs font-medium text-slate-400"
                    >
                      Objective
                    </label>
                    <input
                      id={`phase-objective-${idx}`}
                      type="text"
                      value={phase.objective}
                      onChange={(e) => handlePhaseChange(idx, 'objective', e.target.value)}
                      placeholder="Capture frame timings and memory baseline on long chat threads."
                      className="mt-1 w-full rounded-md border border-[#2A3347] bg-[#0B0F17] px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor={`phase-exit-${idx}`}
                      className="block text-xs font-medium text-slate-400"
                    >
                      Exit Gate
                    </label>
                    <input
                      id={`phase-exit-${idx}`}
                      type="text"
                      value={phase.exitGate}
                      onChange={(e) => handlePhaseChange(idx, 'exitGate', e.target.value)}
                      placeholder="Baseline metrics recorded before any optimization edits."
                      className="mt-1 w-full rounded-md border border-[#2A3347] bg-[#0B0F17] px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-[#232836]">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#2A3347] bg-[#141A29] px-4 py-2 text-sm font-medium text-slate-200 hover:bg-[#1B2233]"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 focus-visible:outline-2 focus-visible:outline-blue-500"
            >
              Save Skill
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
