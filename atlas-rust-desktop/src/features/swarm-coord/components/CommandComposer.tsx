import { useState } from 'react';
import { Check, Copy, RotateCcw, Trash2 } from 'lucide-react';
import { composeCommand, getGlobalFlags, type SkillSpec } from '../utils/skillParser';

export interface CommandHistoryItem {
  id: string;
  commandText: string;
  skillId: string;
  createdAt: string;
}

interface CommandComposerProps {
  skill: SkillSpec;
  history: CommandHistoryItem[];
  onRecordHistory: (commandText: string, skillId: string) => void;
  onClearHistory: () => void;
}

export function CommandComposer({
  skill,
  history,
  onRecordHistory,
  onClearHistory,
}: CommandComposerProps) {
  const [taskInput, setTaskInput] = useState('');
  const [selectedFlags, setSelectedFlags] = useState<string[]>(
    skill.flags.includes('--strict') ? ['--strict'] : []
  );
  const [copied, setCopied] = useState(false);

  const availableFlags = Array.from(new Set([...skill.flags, ...getGlobalFlags()]));
  const composed = composeCommand(skill.command, taskInput, selectedFlags);

  const toggleFlag = (flag: string) => {
    setSelectedFlags((current) =>
      current.includes(flag) ? current.filter((item) => item !== flag) : [...current, flag]
    );
  };

  const handleCopy = async () => {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(composed);
      }
    } catch {
      // Clipboard API may be restricted in headless contexts; still record history.
    }
    onRecordHistory(composed, skill.id);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  const handleCopySaved = async (text: string) => {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      }
    } catch {
      // No-op fallback
    }
  };

  return (
    <section
      aria-labelledby="composer-heading"
      className="rounded-xl border border-[#232836] bg-[#111622] p-6 space-y-5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 id="composer-heading" className="text-base font-semibold text-slate-100">
            Command Composer
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            Build a slash command to paste directly into chat for{' '}
            <span className="font-mono text-slate-200">atlas-chat</span>.
          </p>
        </div>
        {(taskInput || selectedFlags.length > 0) && (
          <button
            type="button"
            onClick={() => {
              setTaskInput('');
              setSelectedFlags([]);
            }}
            className="inline-flex items-center gap-1.5 rounded-md border border-[#2A3347] bg-[#171E2F] px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500 hover:text-white whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-blue-500"
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
            Reset
          </button>
        )}
      </div>

      <div className="space-y-4">
        <div>
          <label htmlFor="composer-task-input" className="block text-sm font-medium text-slate-300">
            Feature, Scope, or Target
          </label>
          <input
            id="composer-task-input"
            type="text"
            value={taskInput}
            onChange={(event) => setTaskInput(event.target.value)}
            placeholder={`Describe the atlas-chat task for ${skill.command}...`}
            className="mt-1.5 w-full rounded-lg border border-[#2A3347] bg-[#0B0F17] px-3.5 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30"
          />
        </div>

        <div>
          <span className="block text-xs font-medium text-slate-400 mb-2">Modifier Flags</span>
          <div className="flex flex-wrap items-center gap-2">
            {availableFlags.map((flag) => {
              const active = selectedFlags.includes(flag);
              return (
                <button
                  key={flag}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleFlag(flag)}
                  className={`rounded-md border px-3 py-1.5 font-mono text-xs font-medium transition-colors whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-blue-500 ${
                    active
                      ? 'border-blue-500 bg-blue-600/20 text-blue-200'
                      : 'border-[#2A3347] bg-[#141A29] text-slate-300 hover:border-slate-500 hover:bg-[#1B2233] hover:text-white'
                  }`}
                >
                  {flag}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-lg border border-[#232836] bg-[#0B0F17] px-4 py-3">
          <code
            data-testid="composed-command"
            className="text-sm text-blue-200 break-all leading-relaxed"
          >
            {composed}
          </code>
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 transition-colors whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
          >
            {copied ? (
              <>
                <Check className="h-4 w-4" aria-hidden="true" />
                Copied
              </>
            ) : (
              <>
                <Copy className="h-4 w-4" aria-hidden="true" />
                Copy Command
              </>
            )}
          </button>
        </div>
      </div>

      {history.length > 0 && (
        <div className="pt-4 border-t border-[#232836]">
          <div className="flex items-center justify-between gap-2 mb-2.5">
            <h3 className="text-xs font-semibold text-slate-400">Recent Invocations</h3>
            <button
              type="button"
              onClick={onClearHistory}
              className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white focus-visible:outline-2 focus-visible:outline-blue-500 rounded px-1.5 py-0.5"
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              Clear History
            </button>
          </div>
          <ul className="divide-y divide-[#1E2433]" data-testid="recent-invocations">
            {history.slice(0, 5).map((entry) => (
              <li
                key={entry.id}
                className="flex items-center justify-between gap-3 py-2 text-xs"
              >
                <code className="text-slate-300 truncate">{entry.commandText}</code>
                <button
                  type="button"
                  onClick={() => handleCopySaved(entry.commandText)}
                  aria-label={`Copy saved command ${entry.commandText}`}
                  className="text-blue-400 hover:underline font-medium whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-blue-500 rounded px-1"
                >
                  Copy
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
