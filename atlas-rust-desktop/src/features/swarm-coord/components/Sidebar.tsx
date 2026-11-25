import { Search, X } from 'lucide-react';
import type { SkillSpec } from '../utils/skillParser';
import type { RepoDoc } from '../data/repoFiles';

export type ActiveSelection =
  | { type: 'skill'; id: string }
  | { type: 'board' }
  | { type: 'doc'; id: string };

interface SidebarProps {
  skills: SkillSpec[];
  filteredSkills: SkillSpec[];
  docs: RepoDoc[];
  selection: ActiveSelection;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  onSelect: (selection: ActiveSelection) => void;
  claimedCount: number;
  conflictCount: number;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function Sidebar({
  skills,
  filteredSkills,
  docs,
  selection,
  searchQuery,
  onSearchChange,
  onSelect,
  claimedCount,
  conflictCount,
  mobileOpen,
  onCloseMobile,
}: SidebarProps) {
  const handleSelect = (next: ActiveSelection) => {
    onSelect(next);
    onCloseMobile();
  };

  const sidebarContent = (
    <div className="flex h-full flex-col bg-[#0E131F] border-r border-[#232836]">
      <div className="p-4 border-b border-[#232836]">
        <label htmlFor="skill-search-input" className="sr-only">
          Search repository skills
        </label>
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500"
            aria-hidden="true"
          />
          <input
            id="skill-search-input"
            type="search"
            value={searchQuery}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Filter skills or roles..."
            className="w-full rounded-lg border border-[#232836] bg-[#141A29] py-2 pl-9 pr-8 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:bg-[#171E2F] focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => onSearchChange('')}
              aria-label="Clear skill filter"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 hover:text-slate-100 focus-visible:outline-2 focus-visible:outline-blue-500"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      <nav aria-label="Workspace navigation" className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
        <div>
          <div className="px-2 pb-2 flex items-center justify-between text-xs font-medium text-slate-400">
            <span>Multi-Session Sync</span>
          </div>
          <button
            type="button"
            onClick={() => handleSelect({ type: 'board' })}
            aria-current={selection.type === 'board' ? 'page' : undefined}
            className={`w-full text-left rounded-lg border px-3 py-2.5 transition-colors focus-visible:outline-2 focus-visible:outline-blue-500 ${
              selection.type === 'board'
                ? 'border-blue-500/40 bg-blue-600/15 text-blue-100'
                : 'border-transparent bg-transparent text-slate-200 hover:border-[#232836] hover:bg-[#161C2C]'
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold truncate">Coordination Board</span>
              <span className="font-mono text-xs tabular-nums text-slate-400 whitespace-nowrap shrink-0">
                {claimedCount} active
              </span>
            </div>
            <p className="mt-0.5 text-xs text-slate-400 truncate">
              {conflictCount > 0
                ? `${conflictCount} path conflict${conflictCount === 1 ? '' : 's'} detected`
                : 'atlas-chat locks & handoffs'}
            </p>
          </button>
        </div>

        <div>
          <div className="px-2 pb-2 flex items-center justify-between text-xs font-medium text-slate-400">
            <span>Workflow Skills</span>
            <span className="font-mono tabular-nums">
              {filteredSkills.length}/{skills.length}
            </span>
          </div>

          {filteredSkills.length === 0 ? (
            <div className="px-2 py-4 text-xs text-slate-400 space-y-2">
              <p>No skills match &ldquo;{searchQuery}&rdquo;.</p>
              <button
                type="button"
                onClick={() => onSearchChange('')}
                className="text-blue-400 font-medium hover:underline focus-visible:outline-2 focus-visible:outline-blue-500"
              >
                Clear Search
              </button>
            </div>
          ) : (
            <ul className="space-y-1">
              {filteredSkills.map((skill) => {
                const isActive = selection.type === 'skill' && selection.id === skill.id;
                return (
                  <li key={skill.id}>
                    <button
                      type="button"
                      onClick={() => handleSelect({ type: 'skill', id: skill.id })}
                      aria-current={isActive ? 'page' : undefined}
                      className={`w-full text-left rounded-lg border px-3 py-2 transition-colors focus-visible:outline-2 focus-visible:outline-blue-500 ${
                        isActive
                          ? 'border-blue-500/40 bg-blue-600/15 text-blue-100'
                          : 'border-transparent bg-transparent text-slate-200 hover:border-[#232836] hover:bg-[#161C2C]'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className={`font-mono text-sm font-semibold truncate ${isActive ? 'text-blue-300' : 'text-slate-100'}`}>
                          {skill.command}
                        </span>
                        <span className="text-xs text-slate-400 tabular-nums whitespace-nowrap shrink-0">
                          {skill.phases.length} steps
                        </span>
                      </div>
                      <p className="mt-0.5 text-xs text-slate-400 truncate">
                        {skill.title}
                        {skill.isCustom ? ' · Custom' : ''}
                      </p>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div>
          <div className="px-2 pb-2 text-xs font-medium text-slate-400">Repository Files</div>
          <ul className="space-y-1">
            {docs.map((doc) => {
              const isActive = selection.type === 'doc' && selection.id === doc.id;
              return (
                <li key={doc.id}>
                  <button
                    type="button"
                    onClick={() => handleSelect({ type: 'doc', id: doc.id })}
                    aria-current={isActive ? 'page' : undefined}
                    className={`w-full text-left rounded-lg border px-3 py-2 transition-colors focus-visible:outline-2 focus-visible:outline-blue-500 ${
                      isActive
                        ? 'border-blue-500/40 bg-blue-600/15 text-blue-100'
                        : 'border-transparent bg-transparent text-slate-300 hover:border-[#232836] hover:bg-[#161C2C] hover:text-white'
                    }`}
                  >
                    <span className="block font-mono text-xs font-medium truncate">
                      {doc.title}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      </nav>
    </div>
  );

  return (
    <>
      <aside className="hidden lg:block w-68 shrink-0">{sidebarContent}</aside>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 flex lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Workspace navigation drawer"
        >
          <div
            className="fixed inset-0 bg-black/60"
            onClick={onCloseMobile}
            aria-hidden="true"
          />
          <div className="relative z-10 flex w-72 max-w-[85vw] flex-col bg-[#0E131F] shadow-xl">
            <div className="flex items-center justify-between border-b border-[#232836] px-4 py-3">
              <span className="text-sm font-semibold text-slate-100">atlas-chat Skills</span>
              <button
                type="button"
                onClick={onCloseMobile}
                aria-label="Close navigation menu"
                className="rounded-md p-2 text-slate-400 hover:bg-[#161C2C] hover:text-slate-100 focus-visible:outline-2 focus-visible:outline-blue-500"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            <div className="flex-1 overflow-hidden">{sidebarContent}</div>
          </div>
        </div>
      )}
    </>
  );
}
