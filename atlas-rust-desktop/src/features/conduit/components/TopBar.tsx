import { ChevronRight, Menu } from 'lucide-react';
import { ActiveView } from '../types/orchestrator';

interface TopBarProps {
  activeView: ActiveView;
  projectName: string;
  onNavigate: (view: ActiveView) => void;
  onOpenMobileMenu: () => void;
  primaryActionLabel: string;
  onPrimaryAction: () => void;
  primaryActionDisabled?: boolean;
}

const VIEW_LABELS: Record<ActiveView, string> = {
  overview: 'Agent Orchestration Dashboard',
  workstreams: 'Workstreams & Git Staging',
  pipeline: 'Production Rollout Pipeline',
  swarm: 'Unified Swarm Board',
  ctf: 'Atlas CTF (/ctf)',
};

export function TopBar({
  activeView,
  projectName,
  onNavigate,
  onOpenMobileMenu,
  primaryActionLabel,
  onPrimaryAction,
  primaryActionDisabled = false,
}: TopBarProps) {
  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between gap-4 border-b border-[#20242E] bg-[#0D0F13]/95 px-4 backdrop-blur-sm sm:px-6">
      <div className="flex min-w-0 items-center gap-2 text-[13.5px]">
        <button
          type="button"
          onClick={onOpenMobileMenu}
          aria-label="Open navigation menu"
          className="rounded-md p-2 text-[#9CA3AF] hover:bg-[#191D26] hover:text-white lg:hidden"
        >
          <Menu className="h-4 w-4" aria-hidden="true" />
        </button>

        {/* Clickable Conduit root link to always jump back to Agent Orchestration Dashboard */}
        <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5">
          <button
            type="button"
            onClick={() => onNavigate('overview')}
            className="font-semibold text-[#F9FAFB] transition-colors hover:text-blue-400 whitespace-nowrap shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded px-1"
          >
            Conduit
          </button>
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[#4B5563]" aria-hidden="true" />
          <span className="hidden font-mono text-[12.5px] text-[#9CA3AF] sm:inline whitespace-nowrap shrink-0">
            {projectName}
          </span>
          <ChevronRight
            className="hidden h-3.5 w-3.5 shrink-0 text-[#4B5563] sm:inline"
            aria-hidden="true"
          />
          <span className="truncate font-medium text-[#D1D5DB]">
            {VIEW_LABELS[activeView]}
          </span>
        </nav>
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <button
          type="button"
          onClick={onPrimaryAction}
          disabled={primaryActionDisabled}
          className="rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-[#232836] disabled:text-[#6B7280] whitespace-nowrap shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
        >
          {primaryActionLabel}
        </button>
      </div>
    </header>
  );
}
