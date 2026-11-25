import {
  GitBranch,
  Layers,
  LayoutDashboard,
  MessageSquareCode,
  Rocket,
  Shield,
  X,
} from 'lucide-react';
import { ActiveView, OrchestratorState } from '../types/orchestrator';
import { ReadinessSummary } from '../utils/orchestrator';

interface SidebarProps {
  activeView: ActiveView;
  onNavigate: (view: ActiveView) => void;
  state: OrchestratorState;
  readiness: ReadinessSummary;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function Sidebar({
  activeView,
  onNavigate,
  state,
  readiness,
  mobileOpen,
  onCloseMobile,
}: SidebarProps) {
  const navItems: Array<{
    id: ActiveView;
    label: string;
    icon: typeof LayoutDashboard;
    meta?: string;
  }> = [
    {
      id: 'overview',
      label: 'Conduit Dashboard',
      icon: LayoutDashboard,
    },
    {
      id: 'workstreams',
      label: 'Workstreams',
      icon: GitBranch,
      meta: `${readiness.committedCount}/${readiness.selectedCount}`,
    },
    {
      id: 'pipeline',
      label: 'Rollout Pipeline',
      icon: Rocket,
      meta:
        state.pipeline.status === 'live'
          ? '100%'
          : state.pipeline.status === 'awaiting_approval'
            ? 'Gate'
            : `${readiness.featuresVerified}/${readiness.featuresTotal}`,
    },
    {
      id: 'swarm',
      label: 'Swarm Board',
      icon: MessageSquareCode,
      meta: `${state.messages.length}`,
    },
    {
      id: 'ctf',
      label: 'Atlas CTF',
      icon: Shield,
      meta: '/ctf',
    },
  ];

  const handleSelect = (view: ActiveView) => {
    onNavigate(view);
    onCloseMobile();
  };

  const sidebarContent = (
    <div className="flex h-full flex-col bg-[#11141A] text-[#E5E7EB]">
      {/* Clickable Conduit Orchestrator entry element */}
      <div className="flex items-center justify-between border-b border-[#20242E] px-5 py-4">
        <button
          type="button"
          onClick={() => handleSelect('overview')}
          aria-label="Open Conduit Agent Orchestration Dashboard"
          className="group flex items-center gap-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded-md"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-blue-500/30 bg-blue-500/10 text-blue-400 transition-colors group-hover:border-blue-400/50 group-hover:bg-blue-500/20">
            <Layers className="h-4 w-4" aria-hidden="true" />
          </span>
          <span className="text-[16px] font-semibold tracking-tight text-[#F9FAFB] whitespace-nowrap group-hover:text-blue-300 transition-colors">
            Conduit
          </span>
        </button>

        <button
          type="button"
          onClick={onCloseMobile}
          aria-label="Close navigation menu"
          className="rounded-md p-1.5 text-[#9CA3AF] hover:bg-[#1C202A] hover:text-white lg:hidden"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      {/* Primary Workspace Navigation */}
      <nav aria-label="Workspace navigation" className="flex-1 space-y-1 px-3 py-4">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeView === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => handleSelect(item.id)}
              aria-current={isActive ? 'page' : undefined}
              className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-[13.5px] font-medium transition-colors whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                isActive
                  ? 'bg-[#1C212C] text-[#F9FAFB]'
                  : 'text-[#9CA3AF] hover:bg-[#171B24] hover:text-[#E5E7EB]'
              }`}
            >
              <span className="flex items-center gap-2.5 min-w-0">
                <Icon
                  className={`h-4 w-4 shrink-0 ${isActive ? 'text-blue-400' : 'text-[#6B7280]'}`}
                  aria-hidden="true"
                />
                <span className="truncate">{item.label}</span>
              </span>
              {item.meta && (
                <span className="font-mono text-[11.5px] tabular-nums text-[#6B7280]">
                  {item.meta}
                </span>
              )}
            </button>
          );
        })}

        {/* Target Repository & Branch Summary */}
        <div className="mt-6 border-t border-[#1E222C] pt-5 px-2">
          <p className="text-[12px] font-medium text-[#6B7280]">Target Repository</p>
          <p className="mt-1 font-mono text-[12.5px] text-[#E5E7EB] truncate">
            {state.projectName}
          </p>
          <p className="mt-0.5 font-mono text-[11px] text-[#8B92A5] truncate">
            {state.repoBranch}
          </p>

          <div className="mt-4 space-y-2 border-t border-[#1E222C] pt-4">
            <p className="text-[12px] font-medium text-[#6B7280]">Orchestrated Providers</p>
            <div className="space-y-1.5 text-[12.5px]">
              <div className="flex items-center justify-between text-[#D1D5DB]">
                <span>Google Chat & Gemini</span>
                <span className="font-mono text-[11px] tabular-nums text-[#8B92A5]">
                  {state.workstreams.filter((w) => w.provider === 'google').length} streams
                </span>
              </div>
              <div className="flex items-center justify-between text-[#D1D5DB]">
                <span>ChatGPT / OpenAI</span>
                <span className="font-mono text-[11px] tabular-nums text-[#8B92A5]">
                  {state.workstreams.filter((w) => w.provider === 'chatgpt').length} streams
                </span>
              </div>
              <div className="flex items-center justify-between text-[#D1D5DB]">
                <span>Local Rust & Ollama</span>
                <span className="font-mono text-[11px] tabular-nums text-[#8B92A5]">
                  {state.workstreams.filter((w) => w.provider === 'local').length} streams
                </span>
              </div>
            </div>
          </div>
        </div>
      </nav>

      {/* Bottom Release Readiness Footer */}
      <div className="border-t border-[#20242E] px-5 py-4">
        <div className="flex items-center justify-between text-[12px]">
          <span className="text-[#9CA3AF]">Release Target</span>
          <span className="font-mono text-[11.5px] tabular-nums text-[#D1D5DB]">
            {readiness.featuresVerified}/{readiness.featuresTotal} verified
          </span>
        </div>
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-[#1E232E]">
          <div
            className="h-full rounded-full bg-blue-500 transition-all duration-300"
            style={{
              width: `${Math.round(
                (readiness.featuresVerified / Math.max(1, readiness.featuresTotal)) * 100
              )}%`,
            }}
          />
        </div>
        <p className="mt-2 font-mono text-[11px] text-[#6B7280] truncate">
          {state.releaseTarget}
        </p>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Sidebar */}
      <aside className="hidden w-[252px] shrink-0 border-r border-[#20242E] lg:block">
        {sidebarContent}
      </aside>

      {/* Mobile Slide-Over Sidebar */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation menu">
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-xs"
            onClick={onCloseMobile}
          />
          <div className="relative z-10 w-[264px] max-w-[82vw] border-r border-[#20242E]">
            {sidebarContent}
          </div>
        </div>
      )}
    </>
  );
}
