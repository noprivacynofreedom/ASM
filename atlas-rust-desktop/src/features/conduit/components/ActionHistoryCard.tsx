import { useState } from 'react';
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  Download,
  FileText,
  FlaskConical,
  GitCommitHorizontal,
  Lightbulb,
  ListChecks,
  Pencil,
  Puzzle,
  Rocket,
  TerminalSquare,
} from 'lucide-react';
import { ActionHistoryBlock, ActionHistoryGroup } from '../types/orchestrator';

interface ActionHistoryCardProps {
  block: ActionHistoryBlock;
  defaultExpanded?: boolean;
}

function GroupIcon({ kind }: { kind: ActionHistoryGroup['kind'] }) {
  const iconClass = 'h-4 w-4 text-[#8E939E] shrink-0';
  switch (kind) {
    case 'tool':
      return <Puzzle className={iconClass} aria-hidden="true" />;
    case 'read':
      return <FileText className={iconClass} aria-hidden="true" />;
    case 'thought':
      return <Lightbulb className={iconClass} aria-hidden="true" />;
    case 'error':
      return <AlertCircle className="h-4 w-4 text-[#EF4444] shrink-0" aria-hidden="true" />;
    case 'install':
      return <Download className={iconClass} aria-hidden="true" />;
    case 'edit':
      return <Pencil className={iconClass} aria-hidden="true" />;
    case 'test':
      return <FlaskConical className={iconClass} aria-hidden="true" />;
    case 'git':
      return <GitCommitHorizontal className={iconClass} aria-hidden="true" />;
    case 'deploy':
      return <Rocket className={iconClass} aria-hidden="true" />;
  }
}

export function ActionHistoryCard({ block, defaultExpanded = true }: ActionHistoryCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expandedThoughts, setExpandedThoughts] = useState<Record<number, boolean>>({});

  const handleCopyTraceId = (traceId: string) => {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(traceId).catch(() => {});
    }
    setCopiedId(traceId);
    setTimeout(() => setCopiedId(null), 1600);
  };

  const toggleThought = (idx: number) => {
    setExpandedThoughts((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const headerTitle = block.headerTitle ?? 'Action history';

  return (
    <div className="mt-3.5">
      {/* Clean Google-inspired attribution header */}
      <div className="mb-2 flex items-center gap-2 text-[12.5px] text-[#9A9FA9]">
        <span className="font-medium text-[#D1D5DB]">{block.modelName}</span>
        <span aria-hidden="true">·</span>
        <span className="font-mono text-[12px] tabular-nums text-[#8B909B]">
          {block.durationLabel}
        </span>
      </div>

      {/* Sleek matte graphite Action History card */}
      <div className="overflow-hidden rounded-2xl border border-[#2A2D34] bg-[#15171B]">
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          aria-expanded={expanded}
          className="flex w-full items-center justify-between gap-3 border-b border-[#24272E] px-4 py-3 text-left transition-colors hover:bg-[#1B1E24] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/60"
        >
          <span className="flex items-center gap-2.5 text-[13.5px] font-medium text-[#D1D5DB]">
            {headerTitle.toLowerCase() === 'working' ? (
              <TerminalSquare className="h-4 w-4 text-[#9A9FA9]" aria-hidden="true" />
            ) : (
              <ListChecks className="h-4 w-4 text-[#9A9FA9]" aria-hidden="true" />
            )}
            <span>{headerTitle}</span>
          </span>
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-[#6B7280]" aria-hidden="true" />
          ) : (
            <ChevronRight className="h-4 w-4 text-[#6B7280]" aria-hidden="true" />
          )}
        </button>

        {expanded && (
          <div className="space-y-3.5 px-4 py-4">
            {block.summary && (
              <p className="text-[13.5px] text-[#9A9FA9]">{block.summary}</p>
            )}

            <div className="space-y-3">
              {block.groups.map((group, idx) => {
                const hasDetail = Boolean(group.detail);
                const isThoughtOpen = Boolean(expandedThoughts[idx]);

                return (
                  <div key={`${group.heading}-${idx}`} className="space-y-2">
                    <div className="flex items-center justify-between gap-3">
                      {hasDetail ? (
                        <button
                          type="button"
                          onClick={() => toggleThought(idx)}
                          aria-expanded={isThoughtOpen}
                          className="flex min-w-0 items-center gap-2.5 text-left text-[13.5px] text-[#B4B9C2] transition-colors hover:text-[#E5E7EB]"
                        >
                          <GroupIcon kind={group.kind} />
                          <span className="truncate">{group.heading}</span>
                          {isThoughtOpen ? (
                            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[#6B7280]" aria-hidden="true" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[#6B7280]" aria-hidden="true" />
                          )}
                        </button>
                      ) : (
                        <div className="flex min-w-0 items-center gap-2.5 text-[13.5px] text-[#B4B9C2]">
                          <GroupIcon kind={group.kind} />
                          <span
                            className={`truncate ${
                              group.kind === 'error' ? 'text-[#FCA5A5]' : 'text-[#C4C9D2]'
                            }`}
                          >
                            {group.heading}
                          </span>
                        </div>
                      )}

                      {group.traceId && (
                        <button
                          type="button"
                          onClick={() => handleCopyTraceId(group.traceId!)}
                          aria-label={`Copy ID ${group.traceId}`}
                          className="inline-flex shrink-0 items-center gap-1.5 rounded-md px-1.5 py-0.5 font-mono text-[11.5px] tabular-nums text-[#8B909B] transition-colors hover:bg-[#22252D] hover:text-[#E5E7EB]"
                        >
                          {copiedId === group.traceId ? (
                            <Check className="h-3.5 w-3.5 text-[#22C55E]" aria-hidden="true" />
                          ) : (
                            <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                          )}
                          <span>ID: {group.traceId}</span>
                        </button>
                      )}
                    </div>

                    {hasDetail && isThoughtOpen && (
                      <p className="ml-6.5 rounded-lg border border-[#24272F] bg-[#111317] px-3 py-2 text-[12.5px] leading-relaxed text-[#9A9FA9]">
                        {group.detail}
                      </p>
                    )}

                    {group.items && group.items.length > 0 && (
                      <ul className="space-y-2 pl-6.5 pt-0.5">
                        {group.items.map((item, itemIdx) => (
                          <li
                            key={`${item.label}-${itemIdx}`}
                            className="flex items-center justify-between gap-4 text-[13px]"
                          >
                            <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-[#B8BEC9]">
                              {item.label}
                            </span>

                            <div className="flex shrink-0 items-center gap-3">
                              {item.meta && (
                                <span className="font-mono text-[11px] tabular-nums text-[#6E7480]">
                                  {item.meta}
                                </span>
                              )}
                              {item.status === 'done' && (
                                <CheckCircle2
                                  className="h-4 w-4 text-[#22C55E]"
                                  aria-label="Completed"
                                />
                              )}
                              {item.status === 'pending' && (
                                <Clock
                                  className="h-4 w-4 text-[#F59E0B]"
                                  aria-label="Pending"
                                />
                              )}
                              {item.status === 'problem' && (
                                <AlertCircle
                                  className="h-4 w-4 text-[#EF4444]"
                                  aria-label="Problem"
                                />
                              )}
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
