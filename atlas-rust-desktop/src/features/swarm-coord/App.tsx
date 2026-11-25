import { useEffect, useMemo, useState } from 'react';
import { Menu, Plus, Trash2 } from 'lucide-react';
import { loadInitialBoardTasks, loadRepoDocs, loadRepoSkills } from './data/repoFiles';
import { filterSkills, type SkillSpec } from './utils/skillParser';
import { detectPathConflicts, type BoardTask } from './utils/boardParser';
import { Sidebar, type ActiveSelection } from './components/Sidebar';
import { CommandComposer, type CommandHistoryItem } from './components/CommandComposer';
import { PipelineView } from './components/PipelineView';
import { CoordinationBoard } from './components/CoordinationBoard';
import { MarkdownViewer } from './components/MarkdownViewer';
import { NewSkillModal } from './components/NewSkillModal';

const STORAGE_KEYS = {
  history: 'atlas-chat:workflow-history:v1',
  customSkills: 'atlas-chat:custom-skills:v1',
  boardTasks: 'atlas-chat:board-tasks:v1',
};

type SkillViewTab = 'workflow' | 'spec' | 'raw';

function readStorage<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export default function App() {
  const repoSkills = useMemo(() => loadRepoSkills(), []);
  const repoDocs = useMemo(() => loadRepoDocs(), []);
  const defaultBoardTasks = useMemo(() => loadInitialBoardTasks(), []);

  const [customSkills, setCustomSkills] = useState<SkillSpec[]>(() =>
    readStorage<SkillSpec[]>(STORAGE_KEYS.customSkills, [])
  );
  const [boardTasks, setBoardTasks] = useState<BoardTask[]>(() =>
    readStorage<BoardTask[]>(STORAGE_KEYS.boardTasks, defaultBoardTasks)
  );
  const [history, setHistory] = useState<CommandHistoryItem[]>(() =>
    readStorage<CommandHistoryItem[]>(STORAGE_KEYS.history, [])
  );

  const allSkills = useMemo(() => [...repoSkills, ...customSkills], [repoSkills, customSkills]);

  const [selection, setSelection] = useState<ActiveSelection>({
    type: 'skill',
    id: repoSkills[0]?.id || 'swarm',
  });
  const [skillTab, setSkillTab] = useState<SkillViewTab>('workflow');
  const [docMode, setDocMode] = useState<'formatted' | 'raw'>('formatted');
  const [searchQuery, setSearchQuery] = useState('');
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [newSkillModalOpen, setNewSkillModalOpen] = useState(false);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEYS.customSkills, JSON.stringify(customSkills));
    } catch {
      // Ignore storage quota issues
    }
  }, [customSkills]);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEYS.boardTasks, JSON.stringify(boardTasks));
    } catch {
      // Ignore storage quota issues
    }
  }, [boardTasks]);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEYS.history, JSON.stringify(history));
    } catch {
      // Ignore storage quota issues
    }
  }, [history]);

  const filteredSkills = useMemo(
    () => filterSkills(allSkills, searchQuery, 'All'),
    [allSkills, searchQuery]
  );

  const selectedSkill =
    selection.type === 'skill'
      ? allSkills.find((skill) => skill.id === selection.id) || allSkills[0]
      : null;

  const selectedDoc =
    selection.type === 'doc' ? repoDocs.find((doc) => doc.id === selection.id) || repoDocs[0] : null;

  const claimedCount = boardTasks.filter((task) => task.status === 'CLAIMED').length;
  const conflictCount = detectPathConflicts(boardTasks).length;

  const handleRecordHistory = (commandText: string, skillId: string) => {
    setHistory((prev) => {
      const filtered = prev.filter((item) => item.commandText !== commandText);
      return [
        {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          commandText,
          skillId,
          createdAt: new Date().toISOString(),
        },
        ...filtered,
      ].slice(0, 12);
    });
  };

  const handleCreateSkill = (skill: SkillSpec) => {
    setCustomSkills((prev) => [...prev, skill]);
    setSelection({ type: 'skill', id: skill.id });
    setSkillTab('workflow');
  };

  const handleDeleteCustomSkill = (skillId: string) => {
    setCustomSkills((prev) => prev.filter((item) => item.id !== skillId));
    setSelection({ type: 'skill', id: repoSkills[0]?.id || 'swarm' });
  };

  return (
    <div className="min-h-full flex flex-col bg-[#0B0F17] text-slate-100">
      <header className="sticky top-0 z-30 flex items-center justify-between gap-8 border-b border-[#232836] bg-[#101521] px-4 sm:px-6 h-14">
        <div className="flex items-center gap-3 min-w-0">
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open navigation menu"
            className="lg:hidden rounded-md p-2 -ml-2 text-slate-400 hover:bg-[#1A2133] hover:text-slate-100 focus-visible:outline-2 focus-visible:outline-blue-500"
          >
            <Menu className="h-5 w-5" aria-hidden="true" />
          </button>
          <a
            href="#workspace-main"
            onClick={(e) => {
              e.preventDefault();
              setSelection({ type: 'skill', id: repoSkills[0]?.id || 'swarm' });
            }}
            className="text-base font-bold tracking-tight text-slate-100 whitespace-nowrap shrink-0"
          >
            atlas-chat Workflows
          </a>
        </div>

        <nav
          aria-label="Primary sections"
          className="hidden md:flex items-center gap-2 text-sm font-medium text-slate-400"
        >
          <button
            type="button"
            onClick={() => setSelection({ type: 'skill', id: 'swarm' })}
            className={`px-3 py-1.5 rounded-md transition-colors whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-blue-500 ${
              selection.type === 'skill' && selection.id === 'swarm'
                ? 'bg-blue-600/20 text-blue-200 border border-blue-500/40'
                : 'text-slate-300 hover:bg-[#1A2133] hover:text-white'
            }`}
          >
            Swarm
          </button>
          <button
            type="button"
            onClick={() => setSelection({ type: 'skill', id: 'sync' })}
            className={`px-3 py-1.5 rounded-md transition-colors whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-blue-500 ${
              selection.type === 'skill' && selection.id === 'sync'
                ? 'bg-blue-600/20 text-blue-200 border border-blue-500/40'
                : 'text-slate-300 hover:bg-[#1A2133] hover:text-white'
            }`}
          >
            Session Sync
          </button>
          <button
            type="button"
            onClick={() => setSelection({ type: 'board' })}
            className={`px-3 py-1.5 rounded-md transition-colors whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-blue-500 ${
              selection.type === 'board'
                ? 'bg-blue-600/20 text-blue-200 border border-blue-500/40'
                : 'text-slate-300 hover:bg-[#1A2133] hover:text-white'
            }`}
          >
            Board
          </button>
          <button
            type="button"
            onClick={() => setSelection({ type: 'doc', id: 'agents' })}
            className={`px-3 py-1.5 rounded-md transition-colors whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-blue-500 ${
              selection.type === 'doc' && selection.id === 'agents'
                ? 'bg-blue-600/20 text-blue-200 border border-blue-500/40'
                : 'text-slate-300 hover:bg-[#1A2133] hover:text-white'
            }`}
          >
            AGENTS.md
          </button>
        </nav>

        <div className="flex items-center shrink-0">
          <button
            type="button"
            onClick={() => setNewSkillModalOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-xs font-medium text-white hover:bg-blue-500 transition-colors whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            New Skill
          </button>
        </div>
      </header>

      <div className="flex-1 flex min-h-0">
        <Sidebar
          skills={allSkills}
          filteredSkills={filteredSkills}
          docs={repoDocs}
          selection={selection}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          onSelect={setSelection}
          claimedCount={claimedCount}
          conflictCount={conflictCount}
          mobileOpen={mobileNavOpen}
          onCloseMobile={() => setMobileNavOpen(false)}
        />

        <main
          id="workspace-main"
          className="flex-1 min-w-0 px-4 sm:px-8 py-6 lg:py-8 overflow-y-auto"
        >
          <div className="mx-auto max-w-5xl space-y-6">
            {selection.type === 'board' && (
              <CoordinationBoard
                tasks={boardTasks}
                onUpdateTasks={setBoardTasks}
                onResetBoard={() => setBoardTasks(defaultBoardTasks)}
              />
            )}

            {selection.type === 'doc' && selectedDoc && (
              <div className="space-y-6">
                <header className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 border-b border-[#232836] pb-5">
                  <div className="max-w-2xl">
                    <div className="flex items-center gap-2 text-xs text-slate-400">
                      <span className="font-mono text-slate-300">{selectedDoc.filePath}</span>
                      <span aria-hidden="true">·</span>
                      <span>atlas-chat repository</span>
                    </div>
                    <h1 className="mt-1.5 text-2xl sm:text-3xl font-bold tracking-tight text-slate-100">
                      {selectedDoc.title}
                    </h1>
                    <p className="mt-2 text-sm text-slate-400">{selectedDoc.summary}</p>
                  </div>

                  <div className="inline-flex items-center gap-1 rounded-lg border border-[#232836] bg-[#111622] p-1 self-start">
                    <button
                      type="button"
                      onClick={() => setDocMode('formatted')}
                      className={`rounded-md px-3 py-1.5 text-xs font-medium whitespace-nowrap shrink-0 transition-colors ${
                        docMode === 'formatted'
                          ? 'bg-blue-600 text-white shadow-xs'
                          : 'text-slate-300 hover:bg-[#1B2233] hover:text-white'
                      }`}
                    >
                      Formatted
                    </button>
                    <button
                      type="button"
                      onClick={() => setDocMode('raw')}
                      className={`rounded-md px-3 py-1.5 text-xs font-medium whitespace-nowrap shrink-0 transition-colors ${
                        docMode === 'raw'
                          ? 'bg-blue-600 text-white shadow-xs'
                          : 'text-slate-300 hover:bg-[#1B2233] hover:text-white'
                      }`}
                    >
                      Raw Markdown
                    </button>
                  </div>
                </header>

                <MarkdownViewer
                  filePath={selectedDoc.filePath}
                  content={selectedDoc.rawMarkdown}
                  mode={docMode}
                />
              </div>
            )}

            {selection.type === 'skill' && selectedSkill && (
              <div className="space-y-6">
                <header className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-[#232836] pb-5">
                  <div className="max-w-2xl">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                      <span className="font-mono text-slate-300">{selectedSkill.filePath}</span>
                      <span aria-hidden="true">·</span>
                      <span>{selectedSkill.category}</span>
                      <span aria-hidden="true">·</span>
                      <span className="tabular-nums">{selectedSkill.phases.length} phases</span>
                      {selectedSkill.isCustom && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span className="text-blue-300">Custom Draft</span>
                        </>
                      )}
                    </div>
                    <h1 className="mt-1.5 text-2xl sm:text-3xl font-bold tracking-tight text-slate-100">
                      <span className="font-mono text-blue-400 mr-2">{selectedSkill.command}</span>{' '}
                      <span>{selectedSkill.title}</span>
                    </h1>
                    <p className="mt-2 text-sm text-slate-400 leading-relaxed">
                      {selectedSkill.summary}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 self-start md:self-end">
                    <div
                      role="tablist"
                      aria-label="Skill view mode"
                      className="inline-flex items-center gap-1 rounded-lg border border-[#232836] bg-[#111622] p-1"
                    >
                      <button
                        type="button"
                        role="tab"
                        aria-selected={skillTab === 'workflow'}
                        onClick={() => setSkillTab('workflow')}
                        className={`rounded-md px-3 py-1.5 text-xs font-medium whitespace-nowrap shrink-0 transition-colors focus-visible:outline-2 focus-visible:outline-blue-500 ${
                          skillTab === 'workflow'
                            ? 'bg-blue-600 text-white shadow-xs'
                            : 'text-slate-300 hover:bg-[#1B2233] hover:text-white'
                        }`}
                      >
                        Pipeline
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={skillTab === 'spec'}
                        onClick={() => setSkillTab('spec')}
                        className={`rounded-md px-3 py-1.5 text-xs font-medium whitespace-nowrap shrink-0 transition-colors focus-visible:outline-2 focus-visible:outline-blue-500 ${
                          skillTab === 'spec'
                            ? 'bg-blue-600 text-white shadow-xs'
                            : 'text-slate-300 hover:bg-[#1B2233] hover:text-white'
                        }`}
                      >
                        Specification
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={skillTab === 'raw'}
                        onClick={() => setSkillTab('raw')}
                        className={`rounded-md px-3 py-1.5 text-xs font-medium whitespace-nowrap shrink-0 transition-colors focus-visible:outline-2 focus-visible:outline-blue-500 ${
                          skillTab === 'raw'
                            ? 'bg-blue-600 text-white shadow-xs'
                            : 'text-slate-300 hover:bg-[#1B2233] hover:text-white'
                        }`}
                      >
                        Raw Markdown
                      </button>
                    </div>

                    {selectedSkill.isCustom && (
                      <button
                        type="button"
                        onClick={() => handleDeleteCustomSkill(selectedSkill.id)}
                        aria-label={`Delete custom skill ${selectedSkill.command}`}
                        className="rounded-lg border border-[#232836] bg-[#111622] p-2 text-slate-400 hover:border-red-500/40 hover:text-red-400 focus-visible:outline-2 focus-visible:outline-blue-500"
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </button>
                    )}
                  </div>
                </header>

                {skillTab === 'workflow' && (
                  <div className="space-y-6">
                    <CommandComposer
                      key={selectedSkill.id}
                      skill={selectedSkill}
                      history={history}
                      onRecordHistory={handleRecordHistory}
                      onClearHistory={() => setHistory([])}
                    />
                    <PipelineView key={`pipeline-${selectedSkill.id}`} skill={selectedSkill} />
                  </div>
                )}

                {skillTab === 'spec' && (
                  <MarkdownViewer
                    filePath={selectedSkill.filePath}
                    content={selectedSkill.rawMarkdown}
                    mode="formatted"
                  />
                )}

                {skillTab === 'raw' && (
                  <MarkdownViewer
                    filePath={selectedSkill.filePath}
                    content={selectedSkill.rawMarkdown}
                    mode="raw"
                  />
                )}
              </div>
            )}
          </div>
        </main>
      </div>

      <NewSkillModal
        open={newSkillModalOpen}
        existingIds={allSkills.map((skill) => skill.id)}
        onClose={() => setNewSkillModalOpen(false)}
        onCreateSkill={handleCreateSkill}
      />
    </div>
  );
}
