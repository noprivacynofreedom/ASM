import { useState } from 'react';
import type { SkillSpec } from '../utils/skillParser';
import { InlineText } from './InlineText';

interface PipelineViewProps {
  skill: SkillSpec;
}

export function PipelineView({ skill }: PipelineViewProps) {
  const [selectedPhaseIndex, setSelectedPhaseIndex] = useState(0);
  const safeIndex = Math.min(selectedPhaseIndex, Math.max(skill.phases.length - 1, 0));
  const activePhase = skill.phases[safeIndex];

  if (skill.phases.length === 0) {
    return (
      <section className="rounded-xl border border-[#232836] bg-[#111622] p-6">
        <p className="text-sm text-slate-400">
          This skill does not define sequential phases yet. Inspect the Specification tab for full
          instructions.
        </p>
      </section>
    );
  }

  return (
    <section
      aria-labelledby="pipeline-heading"
      className="rounded-xl border border-[#232836] bg-[#111622] p-6 space-y-6"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 id="pipeline-heading" className="text-base font-semibold text-slate-100">
            Sequential Role Pipeline
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            Select any phase to inspect role ownership, deliverables, and its mandatory exit gate.
          </p>
        </div>
        <div className="text-xs text-slate-400 tabular-nums">
          {skill.phases.length} sequential phases
        </div>
      </div>

      <div
        role="tablist"
        aria-label={`${skill.command} execution phases`}
        className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-2"
      >
        {skill.phases.map((phase, idx) => {
          const isSelected = idx === safeIndex;
          return (
            <button
              key={`${skill.id}-phase-${phase.index}`}
              type="button"
              role="tab"
              aria-selected={isSelected}
              onClick={() => setSelectedPhaseIndex(idx)}
              className={`text-left rounded-lg border p-3.5 transition-colors focus-visible:outline-2 focus-visible:outline-blue-500 ${
                isSelected
                  ? 'border-blue-500 bg-blue-600/15 text-slate-100'
                  : 'border-[#232836] bg-[#0D121E] text-slate-300 hover:border-[#343E57] hover:bg-[#151C2D]'
              }`}
            >
              <div className="flex items-center justify-between gap-2 text-xs text-slate-400 tabular-nums">
                <span className={`font-mono font-medium ${isSelected ? 'text-blue-300' : ''}`}>0{phase.index}</span>
                <span className="truncate">{phase.role}</span>
              </div>
              <div className="mt-1.5 text-sm font-semibold text-slate-100 leading-snug">
                {phase.title}
              </div>
            </button>
          );
        })}
      </div>

      {activePhase && (
        <div
          role="tabpanel"
          className="pt-5 border-t border-[#232836] grid grid-cols-1 lg:grid-cols-3 gap-6"
        >
          <div className="lg:col-span-2 space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <span className="font-mono font-medium text-blue-300 tabular-nums">
                Phase 0{activePhase.index}
              </span>
              <span aria-hidden="true">·</span>
              <span>Role: {activePhase.role}</span>
            </div>

            <div>
              <h3 className="text-lg font-semibold text-slate-100">{activePhase.title}</h3>
              <p className="mt-1.5 text-sm text-slate-300 leading-relaxed">
                <InlineText text={activePhase.objective} />
              </p>
            </div>

            <div>
              <h4 className="text-xs font-semibold text-slate-400 mb-2">Phase Deliverables</h4>
              <ul className="space-y-2 text-sm text-slate-200">
                {activePhase.deliverables.map((item, idx) => (
                  <li key={idx} className="flex items-start gap-2.5 leading-relaxed">
                    <span
                      className="mt-0.5 font-mono text-xs text-slate-500 tabular-nums select-none"
                      aria-hidden="true"
                    >
                      {idx + 1}.
                    </span>
                    <span>
                      <InlineText text={item} />
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="space-y-5 lg:border-l lg:border-[#232836] lg:pl-6">
            <div>
              <h4 className="text-xs font-semibold text-slate-400">Mandatory Exit Gate</h4>
              <p className="mt-1.5 text-sm text-slate-100 leading-relaxed">
                <InlineText text={activePhase.exitGate} />
              </p>
            </div>

            {skill.guardrails.length > 0 && (
              <div className="pt-4 border-t border-[#232836]">
                <h4 className="text-xs font-semibold text-slate-400">Workflow Guardrails</h4>
                <ul className="mt-2 space-y-2 text-xs text-slate-300 leading-relaxed">
                  {skill.guardrails.map((rule, idx) => (
                    <li key={idx}>
                      <InlineText text={rule} />
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
