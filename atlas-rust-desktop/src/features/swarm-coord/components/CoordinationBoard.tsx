import { useState } from 'react';
import { AlertTriangle, Check, Copy, Plus, RotateCcw } from 'lucide-react';
import {
  buildSessionHandoffPrompt,
  detectPathConflicts,
  serializeBoardMarkdown,
  validateNewBoardTask,
  type BoardTask,
  type NewBoardTaskDraft,
  type TaskStatus,
} from '../utils/boardParser';

interface CoordinationBoardProps {
  tasks: BoardTask[];
  onUpdateTasks: (nextTasks: BoardTask[]) => void;
  onResetBoard: () => void;
}

const STATUS_FILTERS: Array<'ALL' | TaskStatus> = [
  'ALL',
  'TODO',
  'CLAIMED',
  'IN_REVIEW',
  'DONE',
  'BLOCKED',
];

const STATUS_TEXT_CLASS: Record<TaskStatus, string> = {
  TODO: 'text-slate-300',
  CLAIMED: 'text-blue-300',
  IN_REVIEW: 'text-amber-300',
  DONE: 'text-emerald-300',
  BLOCKED: 'text-red-300',
};

const EMPTY_DRAFT: NewBoardTaskDraft = {
  id: '',
  title: '',
  branch: '',
  ownedPathsText: '',
  dependsOnText: '',
};

export function CoordinationBoard({
  tasks,
  onUpdateTasks,
  onResetBoard,
}: CoordinationBoardProps) {
  const [statusFilter, setStatusFilter] = useState<'ALL' | TaskStatus>('ALL');
  const [sessionLabel, setSessionLabel] = useState('session-gemini-04');
  const [copiedTaskId, setCopiedTaskId] = useState<string | null>(null);
  const [copiedBoardMd, setCopiedBoardMd] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [draft, setDraft] = useState<NewBoardTaskDraft>(EMPTY_DRAFT);
  const [draftErrors, setDraftErrors] = useState<Record<string, string>>({});

  const conflicts = detectPathConflicts(tasks);
  const visibleTasks =
    statusFilter === 'ALL' ? tasks : tasks.filter((task) => task.status === statusFilter);

  const countByStatus = (status: TaskStatus) => tasks.filter((t) => t.status === status).length;

  const handleStatusChange = (taskId: string, nextStatus: TaskStatus) => {
    const cleanSession = sessionLabel.trim() || 'session-gemini-04';
    onUpdateTasks(
      tasks.map((task) => {
        if (task.id !== taskId) return task;
        const nextOwner =
          nextStatus === 'CLAIMED'
            ? cleanSession
            : nextStatus === 'TODO'
              ? 'unassigned'
              : task.ownerSession === 'unassigned'
                ? cleanSession
                : task.ownerSession;
        return { ...task, status: nextStatus, ownerSession: nextOwner };
      })
    );
  };

  const handleCopyPrompt = async (task: BoardTask) => {
    const prompt = buildSessionHandoffPrompt(task, tasks, 'atlas-chat');
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(prompt);
      }
    } catch {
      // Fallback when clipboard permission is unavailable
    }
    setCopiedTaskId(task.id);
    window.setTimeout(() => setCopiedTaskId(null), 1800);
  };

  const handleCopyBoardMarkdown = async () => {
    const md = serializeBoardMarkdown(tasks);
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(md);
      }
    } catch {
      // No-op
    }
    setCopiedBoardMd(true);
    window.setTimeout(() => setCopiedBoardMd(false), 1800);
  };

  const handleAddTask = (event: React.FormEvent) => {
    event.preventDefault();
    const validation = validateNewBoardTask(
      draft,
      tasks.map((task) => task.id)
    );
    if (!validation.valid) {
      setDraftErrors(validation.errors);
      return;
    }

    const cleanId = draft.id.trim().toUpperCase();
    const newTask: BoardTask = {
      id: cleanId,
      title: draft.title.trim(),
      status: 'TODO',
      ownerSession: 'unassigned',
      branch: draft.branch.trim() || `swarm/${cleanId.toLowerCase()}`,
      ownedPaths: draft.ownedPathsText
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
      dependsOn: draft.dependsOnText
        .split(',')
        .map((item) => item.trim().toUpperCase())
        .filter(Boolean),
    };

    onUpdateTasks([...tasks, newTask]);
    setDraft(EMPTY_DRAFT);
    setDraftErrors({});
    setShowAddForm(false);
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-[#232836] pb-5">
        <div className="max-w-2xl">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span className="font-mono text-slate-300">/swarm/BOARD.md</span>
            <span aria-hidden="true">·</span>
            <span>Repository: atlas-chat</span>
            <span aria-hidden="true">·</span>
            <span className="tabular-nums">{tasks.length} tasks</span>
          </div>
          <h1 className="mt-1.5 text-2xl sm:text-3xl font-bold tracking-tight text-slate-100">
            Multi-Session Coordination Board
          </h1>
          <p className="mt-2 text-sm text-slate-400 leading-relaxed">
            Separate Gemini sessions cannot share live memory. Coordinate asynchronously on{' '}
            <span className="font-mono text-slate-200">atlas-chat</span> by claiming one task per
            session, locking its file paths, and pasting the generated handoff brief into each
            session.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={handleCopyBoardMarkdown}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[#2A3347] bg-[#141A29] px-3.5 py-2 text-sm font-medium text-slate-200 hover:border-slate-500 hover:text-white whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-blue-500"
          >
            {copiedBoardMd ? (
              <>
                <Check className="h-4 w-4 text-emerald-400" aria-hidden="true" />
                Copied BOARD.md
              </>
            ) : (
              <>
                <Copy className="h-4 w-4" aria-hidden="true" />
                Copy BOARD.md
              </>
            )}
          </button>
          <button
            type="button"
            onClick={() => setShowAddForm((open) => !open)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            Add Task
          </button>
        </div>
      </header>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="rounded-xl border border-[#232836] bg-[#111622] px-4 py-3.5">
          <div className="text-xs text-slate-400">Available (TODO)</div>
          <div className="mt-1 font-mono text-2xl font-semibold text-slate-100 tabular-nums">
            {countByStatus('TODO')}
          </div>
        </div>
        <div className="rounded-xl border border-[#232836] bg-[#111622] px-4 py-3.5">
          <div className="text-xs text-slate-400">Active Locks (CLAIMED)</div>
          <div className="mt-1 font-mono text-2xl font-semibold text-blue-400 tabular-nums">
            {countByStatus('CLAIMED')}
          </div>
        </div>
        <div className="rounded-xl border border-[#232836] bg-[#111622] px-4 py-3.5">
          <div className="text-xs text-slate-400">In Review / Done</div>
          <div className="mt-1 font-mono text-2xl font-semibold text-emerald-400 tabular-nums">
            {countByStatus('IN_REVIEW') + countByStatus('DONE')}
          </div>
        </div>
        <div className="rounded-xl border border-[#232836] bg-[#111622] px-4 py-3.5">
          <div className="text-xs text-slate-400">File-Lock Conflicts</div>
          <div
            className={`mt-1 font-mono text-2xl font-semibold tabular-nums ${
              conflicts.length > 0 ? 'text-red-400' : 'text-slate-100'
            }`}
          >
            {conflicts.length}
          </div>
        </div>
      </div>

      {conflicts.length > 0 && (
        <div
          role="alert"
          className="rounded-xl border border-red-500/30 bg-red-950/40 px-5 py-4 text-sm text-red-100"
        >
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" aria-hidden="true" />
            <div className="space-y-1">
              <p className="font-semibold">File-ownership conflict between active sessions</p>
              <ul className="space-y-1 text-xs text-red-200">
                {conflicts.map((conflict, idx) => (
                  <li key={idx}>
                    <span className="font-mono font-medium">{conflict.path}</span> is claimed by
                    both <span className="font-mono">{conflict.taskIds[0]}</span> (
                    {conflict.sessions[0]}) and{' '}
                    <span className="font-mono">{conflict.taskIds[1]}</span> (
                    {conflict.sessions[1]}). Release one lock or split the paths before running both
                    sessions.
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {showAddForm && (
        <form
          onSubmit={handleAddTask}
          noValidate
          className="rounded-xl border border-[#232836] bg-[#111622] p-6 space-y-4"
        >
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-base font-semibold text-slate-100">Queue Task for atlas-chat</h2>
            <button
              type="button"
              onClick={() => {
                setShowAddForm(false);
                setDraftErrors({});
              }}
              className="text-xs font-medium text-slate-400 hover:text-white"
            >
              Cancel
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label htmlFor="task-id-input" className="block text-xs font-medium text-slate-300">
                Task ID
              </label>
              <input
                id="task-id-input"
                type="text"
                value={draft.id}
                onChange={(e) => setDraft({ ...draft, id: e.target.value })}
                placeholder="T-107"
                className="mt-1 w-full rounded-lg border border-[#2A3347] bg-[#0B0F17] px-3 py-2 font-mono text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
              />
              {draftErrors.id && <p className="mt-1 text-xs text-red-400">{draftErrors.id}</p>}
            </div>

            <div className="sm:col-span-2">
              <label
                htmlFor="task-title-input"
                className="block text-xs font-medium text-slate-300"
              >
                Task Title
              </label>
              <input
                id="task-title-input"
                type="text"
                value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                placeholder="Add typing indicators to active channel header"
                className="mt-1 w-full rounded-lg border border-[#2A3347] bg-[#0B0F17] px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
              />
              {draftErrors.title && (
                <p className="mt-1 text-xs text-red-400">{draftErrors.title}</p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="sm:col-span-2">
              <label
                htmlFor="task-paths-input"
                className="block text-xs font-medium text-slate-300"
              >
                Owned Paths (comma-separated)
              </label>
              <input
                id="task-paths-input"
                type="text"
                value={draft.ownedPathsText}
                onChange={(e) => setDraft({ ...draft, ownedPathsText: e.target.value })}
                placeholder="src/components/TypingIndicator.tsx, src/hooks/useTyping.ts"
                className="mt-1 w-full rounded-lg border border-[#2A3347] bg-[#0B0F17] px-3 py-2 font-mono text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
              />
              {draftErrors.ownedPaths && (
                <p className="mt-1 text-xs text-red-400">{draftErrors.ownedPaths}</p>
              )}
            </div>

            <div>
              <label
                htmlFor="task-deps-input"
                className="block text-xs font-medium text-slate-300"
              >
                Depends On (optional)
              </label>
              <input
                id="task-deps-input"
                type="text"
                value={draft.dependsOnText}
                onChange={(e) => setDraft({ ...draft, dependsOnText: e.target.value })}
                placeholder="T-101"
                className="mt-1 w-full rounded-lg border border-[#2A3347] bg-[#0B0F17] px-3 py-2 font-mono text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="submit"
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 focus-visible:outline-2 focus-visible:outline-blue-500"
            >
              Add to Board
            </button>
          </div>
        </form>
      )}

      <section className="rounded-xl border border-[#232836] bg-[#111622] overflow-hidden">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-[#232836] px-5 py-3.5">
          <div className="flex items-center gap-1 overflow-x-auto p-1 bg-[#0B0F17] border border-[#232836] rounded-lg">
            {STATUS_FILTERS.map((status) => (
              <button
                key={status}
                type="button"
                onClick={() => setStatusFilter(status)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-blue-500 ${
                  statusFilter === status
                    ? 'bg-blue-600 text-white shadow-xs'
                    : 'text-slate-300 hover:bg-[#1B2233] hover:text-white'
                }`}
              >
                {status === 'ALL' ? 'All Tasks' : status.replace('_', ' ')}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <label
                htmlFor="session-label-input"
                className="text-xs font-medium text-slate-400 whitespace-nowrap"
              >
                My Session ID
              </label>
              <input
                id="session-label-input"
                type="text"
                value={sessionLabel}
                onChange={(e) => setSessionLabel(e.target.value)}
                className="w-40 rounded-md border border-[#2A3347] bg-[#0B0F17] px-2.5 py-1 font-mono text-xs text-slate-100 focus:border-blue-500 focus:outline-none"
              />
            </div>
            <button
              type="button"
              onClick={onResetBoard}
              aria-label="Reset coordination board to repository defaults"
              className="inline-flex items-center gap-1 rounded-md border border-[#2A3347] bg-[#141A29] px-2.5 py-1 text-xs font-medium text-slate-300 hover:border-slate-500 hover:text-white whitespace-nowrap shrink-0"
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              Reset
            </button>
          </div>
        </div>

        {visibleTasks.length === 0 ? (
          <div className="px-6 py-10 text-center text-sm text-slate-400">
            No tasks currently in status <span className="font-mono text-slate-200">{statusFilter}</span>.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-[#232836] bg-[#0D121E] text-xs font-medium text-slate-400">
                  <th className="py-3 px-4 whitespace-nowrap">ID</th>
                  <th className="py-3 px-4">Task &amp; Owned Paths</th>
                  <th className="py-3 px-4 whitespace-nowrap">Session Owner</th>
                  <th className="py-3 px-4 whitespace-nowrap">Status</th>
                  <th className="py-3 px-4 text-right whitespace-nowrap">Handoff Prompt</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1E2433] text-sm">
                {visibleTasks.map((task) => (
                  <tr key={task.id} className="hover:bg-[#161C2C] transition-colors">
                    <td className="py-3.5 px-4 align-top font-mono text-xs font-semibold text-blue-300 tabular-nums whitespace-nowrap">
                      {task.id}
                    </td>
                    <td className="py-3.5 px-4 align-top">
                      <div className="font-medium text-slate-100">{task.title}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-400">
                        <span className="font-mono text-slate-300">
                          {task.ownedPaths.join(', ')}
                        </span>
                        {task.dependsOn.length > 0 && (
                          <>
                            <span aria-hidden="true">·</span>
                            <span>Depends on {task.dependsOn.join(', ')}</span>
                          </>
                        )}
                      </div>
                    </td>
                    <td className="py-3.5 px-4 align-top font-mono text-xs text-slate-300 whitespace-nowrap">
                      <div>{task.ownerSession}</div>
                      {task.branch && (
                        <div className="mt-0.5 text-slate-500">{task.branch}</div>
                      )}
                    </td>
                    <td className="py-3.5 px-4 align-top whitespace-nowrap">
                      <label htmlFor={`status-${task.id}`} className="sr-only">
                        Status for {task.id}
                      </label>
                      <select
                        id={`status-${task.id}`}
                        value={task.status}
                        onChange={(e) => handleStatusChange(task.id, e.target.value as TaskStatus)}
                        className={`rounded-md border border-[#2A3347] bg-[#0B0F17] px-2.5 py-1 font-mono text-xs font-medium focus:border-blue-500 focus:outline-none ${STATUS_TEXT_CLASS[task.status]}`}
                      >
                        <option value="TODO">TODO</option>
                        <option value="CLAIMED">CLAIMED</option>
                        <option value="IN_REVIEW">IN_REVIEW</option>
                        <option value="DONE">DONE</option>
                        <option value="BLOCKED">BLOCKED</option>
                      </select>
                    </td>
                    <td className="py-3.5 px-4 align-top text-right whitespace-nowrap">
                      <button
                        type="button"
                        onClick={() => handleCopyPrompt(task)}
                        aria-label={`Copy session prompt for ${task.id}`}
                        className="inline-flex items-center gap-1.5 rounded-md border border-[#2A3347] bg-[#141A29] px-3 py-1.5 text-xs font-medium text-slate-200 hover:border-blue-500/60 hover:text-blue-200 transition-colors focus-visible:outline-2 focus-visible:outline-blue-500"
                      >
                        {copiedTaskId === task.id ? (
                          <>
                            <Check className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
                            Copied Prompt
                          </>
                        ) : (
                          <>
                            <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                            Copy Session Prompt
                          </>
                        )}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
