import { FormEvent, useMemo, useState } from 'react';
import {
  CheckCircle2,
  FileText,
  Hash,
  Send,
  Sparkles,
} from 'lucide-react';
import {
  MessageKind,
  OrchestratorState,
  SwarmChannelId,
} from '../types/orchestrator';
import { filterSwarmMessages } from '../utils/orchestrator';
import { ActionHistoryCard } from './ActionHistoryCard';

interface SwarmBoardViewProps {
  state: OrchestratorState;
  devlogMarkdown: string;
  onPostMessage: (input: {
    channelId: SwarmChannelId;
    senderAgentId: string;
    targetHandle: string;
    kind: MessageKind;
    body: string;
    workstreamId?: string;
    alsoWriteDevlog?: boolean;
  }) => Promise<SwarmChannelId | void>;
  onAcknowledgeMessage: (messageId: string) => void;
  onRequestGeminiReply: (channelId: SwarmChannelId) => Promise<void>;
  geminiReplyLoading: boolean;
  geminiReplyError: string | null;
}

const CHANNELS: Array<{ id: SwarmChannelId; name: string; topic: string }> = [
  { id: 'atlas-integration', name: 'atlas-integration', topic: 'Cross-provider branch sync & commits' },
  { id: 'missing-features', name: 'missing-features', topic: 'Uncommitted patches & feature parity' },
  { id: 'merge-conflicts', name: 'merge-conflicts', topic: 'Registry & diff conflict resolution' },
  { id: 'prod-rollout', name: 'prod-rollout', topic: 'Canary traffic, HotSync & cutover gates' },
  { id: 'devlog-sync', name: 'devlog-sync', topic: 'Shared DEVLOG.md swarm ledger' },
];

const KIND_LABELS: Record<MessageKind, string> = {
  handoff: 'Handoff',
  patch_ready: 'Patch Ready',
  conflict_alert: 'Conflict Alert',
  verification: 'Verification',
  directive: 'Directive',
  devlog_sync: 'Devlog Sync',
};

export function SwarmBoardView({
  state,
  devlogMarkdown,
  onPostMessage,
  onAcknowledgeMessage,
  onRequestGeminiReply,
  geminiReplyLoading,
  geminiReplyError,
}: SwarmBoardViewProps) {
  const [activeChannel, setActiveChannel] = useState<SwarmChannelId>('atlas-integration');
  const [kindFilter, setKindFilter] = useState<MessageKind | 'all'>('all');
  const [showDevlogPane, setShowDevlogPane] = useState(false);

  // Composer state
  const [senderAgentId, setSenderAgentId] = useState<string>('agent-lead');
  const [targetHandle, setTargetHandle] = useState<string>('@all-agents');
  const [messageKind, setMessageKind] = useState<MessageKind>('handoff');
  const [workstreamId, setWorkstreamId] = useState<string>('');
  const [body, setBody] = useState<string>('');
  const [syncToDevlog, setSyncToDevlog] = useState<boolean>(true);
  const [composerError, setComposerError] = useState<string | null>(null);

  const visibleMessages = useMemo(
    () =>
      filterSwarmMessages(state.messages, {
        channelId: activeChannel,
        kind: kindFilter,
        query: '',
      }),
    [state.messages, activeChannel, kindFilter]
  );

  const channelMeta = CHANNELS.find((c) => c.id === activeChannel) ?? CHANNELS[0];

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!body.trim()) {
      setComposerError('Enter a message before dispatching to the swarm.');
      return;
    }
    setComposerError(null);
    const switchedChannel = await onPostMessage({
      channelId: activeChannel,
      senderAgentId,
      targetHandle,
      kind: activeChannel === 'devlog-sync' ? 'devlog_sync' : messageKind,
      body: body.trim(),
      workstreamId: workstreamId || undefined,
      alsoWriteDevlog: syncToDevlog || activeChannel === 'devlog-sync',
    });
    if (switchedChannel) {
      setActiveChannel(switchedChannel);
    }
    setBody('');
  };

  return (
    <div className="mx-auto max-w-[1280px] space-y-6">
      {/* Header */}
      <div className="flex flex-col justify-between gap-4 border-b border-[#20242E] pb-5 lg:flex-row lg:items-end">
        <div className="max-w-2xl">
          <h1 className="text-[22px] font-semibold tracking-tight text-[#F9FAFB]">
            Unified Swarm Board
          </h1>
          <p className="mt-1 text-[13.5px] text-[#9CA3AF]">
            Inter-agent messaging between Google Chat/Gemini, ChatGPT, and Local runners with structured Action History replies and live{' '}
            <span className="font-mono text-[#D1D5DB]">DEVLOG.md</span> synchronization.
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2.5 lg:flex-nowrap">
          <button
            type="button"
            onClick={() => setShowDevlogPane((prev) => !prev)}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-[13px] font-medium transition-colors whitespace-nowrap shrink-0 ${
              showDevlogPane
                ? 'border-blue-500/40 bg-blue-500/10 text-blue-300'
                : 'border-[#2C3240] bg-[#171B24] text-[#E5E7EB] hover:bg-[#1E232F]'
            }`}
          >
            <FileText className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{showDevlogPane ? 'Hide DEVLOG.md' : 'Inspect DEVLOG.md'}</span>
          </button>

          <button
            type="button"
            onClick={() => onRequestGeminiReply(activeChannel)}
            disabled={geminiReplyLoading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-[13px] font-medium text-white transition-colors hover:bg-blue-500 disabled:opacity-60 whitespace-nowrap shrink-0"
          >
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{geminiReplyLoading ? 'Thinking...' : 'Request Gemini Reply'}</span>
          </button>
        </div>
      </div>

      {/* Optional live DEVLOG.md viewer */}
      {showDevlogPane && (
        <section className="rounded-xl border border-[#262B38] bg-[#14171D]">
          <div className="flex items-center justify-between border-b border-[#20242E] px-5 py-3">
            <div className="flex items-center gap-2 text-[13px]">
              <FileText className="h-4 w-4 text-blue-400" aria-hidden="true" />
              <span className="font-mono font-medium text-[#F3F4F6]">DEVLOG.md</span>
              <span className="text-[#6B7280]" aria-hidden="true">·</span>
              <span className="text-[#8B92A5]">Live shared ledger read from repository disk</span>
            </div>
            <span className="font-mono text-[11.5px] text-[#22C55E]">Synced</span>
          </div>
          <pre className="max-h-64 overflow-auto p-5 font-mono text-[12px] leading-relaxed text-[#CBD5E1] whitespace-pre-wrap">
            {devlogMarkdown}
          </pre>
        </section>
      )}

      {geminiReplyError && (
        <div role="alert" className="rounded-xl border border-red-500/30 bg-[#1B1418] px-4 py-3 text-[13px] text-red-300">
          {geminiReplyError}
        </div>
      )}

      {/* 3-Column Swarm Layout: Channels | Message Feed + Composer | Active Agents Roster */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        {/* Channels Sidebar */}
        <aside className="rounded-xl border border-[#222630] bg-[#14171D] p-3 xl:col-span-3 h-fit">
          <p className="px-2.5 py-2 text-[12px] font-medium text-[#6B7280]">Swarm Channels</p>
          <nav aria-label="Swarm channels" className="space-y-1">
            {CHANNELS.map((ch) => {
              const count = state.messages.filter((m) => m.channelId === ch.id).length;
              const isActive = activeChannel === ch.id;
              return (
                <button
                  key={ch.id}
                  type="button"
                  onClick={() => setActiveChannel(ch.id)}
                  aria-current={isActive ? 'true' : undefined}
                  className={`flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors ${
                    isActive
                      ? 'bg-[#1D222E] font-medium text-[#F9FAFB]'
                      : 'text-[#9CA3AF] hover:bg-[#181C25] hover:text-[#E5E7EB]'
                  }`}
                >
                  <span className="flex items-center gap-1.5 min-w-0">
                    <Hash className="h-3.5 w-3.5 shrink-0 text-[#6B7280]" aria-hidden="true" />
                    <span className="truncate font-mono text-[12.5px]">{ch.name}</span>
                  </span>
                  <span className="font-mono text-[11px] tabular-nums text-[#6B7280]">{count}</span>
                </button>
              );
            })}
          </nav>

          {/* Active Agent Roster */}
          <div className="mt-5 border-t border-[#1E222C] pt-4 px-2">
            <p className="text-[12px] font-medium text-[#6B7280]">Active Swarm Roster</p>
            <ul className="mt-3 space-y-3">
              {state.agents.map((agent) => {
                const owned = state.workstreams.filter((w) => w.agentId === agent.id);
                const hasConflict = owned.some((w) => w.conflictState === 'conflict');
                const hasUncommitted = owned.some((w) => w.gitState === 'uncommitted');
                const liveStatus =
                  agent.provider === 'human'
                    ? 'Active'
                    : hasConflict
                      ? 'Conflict'
                      : hasUncommitted
                        ? 'Dirty Tree'
                        : 'Synced';
                const statusColor =
                  liveStatus === 'Synced' || liveStatus === 'Active'
                    ? 'text-[#22C55E]'
                    : liveStatus === 'Conflict'
                      ? 'text-[#EF4444]'
                      : 'text-[#F59E0B]';

                return (
                  <li key={agent.id} className="space-y-0.5">
                    <div className="flex items-center justify-between gap-2 text-[12.5px]">
                      <span className="font-medium text-[#E5E7EB] truncate">{agent.displayName}</span>
                      <span className={`shrink-0 font-mono text-[11px] ${statusColor}`}>
                        {liveStatus}
                      </span>
                    </div>
                    <p className="font-mono text-[11px] text-[#6B7280] truncate">{agent.handle}</p>
                    {agent.claimedTarget && (
                      <p className="font-mono text-[10.5px] text-blue-400 truncate">
                        Claimed: {agent.claimedTarget}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        </aside>

        {/* Main Message Stream & Composer */}
        <section className="flex flex-col rounded-xl border border-[#222630] bg-[#14171D] xl:col-span-9">
          {/* Channel Header & Type Filter */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#20242E] px-5 py-3.5">
            <div>
              <h2 className="font-mono text-[14px] font-semibold text-[#F9FAFB]">
                #{channelMeta.name}
              </h2>
              <p className="text-[12.5px] text-[#8B92A5]">{channelMeta.topic}</p>
            </div>

            <div className="flex items-center gap-2">
              <label htmlFor="kind-filter" className="sr-only">
                Filter messages by type
              </label>
              <select
                id="kind-filter"
                value={kindFilter}
                onChange={(e) => setKindFilter(e.target.value as MessageKind | 'all')}
                className="rounded-lg border border-[#282D3A] bg-[#0F1218] px-3 py-1.5 text-[12.5px] text-[#D1D5DB]"
              >
                <option value="all">All Message Types</option>
                <option value="handoff">Handoffs</option>
                <option value="patch_ready">Patch Ready</option>
                <option value="conflict_alert">Conflict Alerts</option>
                <option value="verification">Verifications</option>
                <option value="devlog_sync">Devlog Sync</option>
                <option value="directive">Directives</option>
              </select>
            </div>
          </div>

          {/* Messages List */}
          <div className="divide-y divide-[#1D212B] flex-1">
            {visibleMessages.length === 0 ? (
              <div className="px-6 py-12 text-center">
                <p className="text-[14px] font-medium text-[#E5E7EB]">
                  No messages in #{activeChannel} yet
                </p>
                <p className="mt-1 text-[13px] text-[#8B92A5]">
                  Dispatch a handoff or request a live Gemini reply below.
                </p>
              </div>
            ) : (
              visibleMessages.map((msg) => {
                const sender = state.agents.find((a) => a.id === msg.senderAgentId);
                const linkedWs = msg.workstreamId
                  ? state.workstreams.find((w) => w.id === msg.workstreamId)
                  : undefined;

                return (
                  <article key={msg.id} className="px-5 py-5">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-[12.5px]">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-[#F9FAFB]">
                          {sender?.displayName ?? 'Agent'}
                        </span>
                        <span className="font-mono text-[11.5px] text-[#6B7280]">
                          {sender?.handle}
                        </span>
                        <span className="text-[#4B5563]" aria-hidden="true">→</span>
                        <span className="font-mono text-[11.5px] text-blue-400">
                          {msg.targetHandle}
                        </span>
                        <span className="text-[#4B5563]" aria-hidden="true">·</span>
                        <span className="text-[#9CA3AF]">{KIND_LABELS[msg.kind]}</span>
                      </div>

                      <div className="flex items-center gap-3">
                        <span className="font-mono text-[11.5px] tabular-nums text-[#6B7280]">
                          {msg.createdAt.slice(11, 16)} UTC
                        </span>
                        {!msg.acknowledged ? (
                          <button
                            type="button"
                            onClick={() => onAcknowledgeMessage(msg.id)}
                            className="rounded-md border border-blue-500/40 bg-blue-500/10 px-2.5 py-1 text-[11.5px] font-medium text-blue-300 hover:bg-blue-500/20 whitespace-nowrap"
                          >
                            Acknowledge
                          </button>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[11.5px] text-[#22C55E]">
                            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                            Ack
                          </span>
                        )}
                      </div>
                    </div>

                    <p className="mt-2.5 text-[14px] leading-relaxed text-[#E5E7EB]">
                      {msg.body}
                    </p>

                    {linkedWs && (
                      <p className="mt-2 font-mono text-[11.5px] text-[#8B92A5]">
                        Workstream: {linkedWs.branch} ({linkedWs.commitSha ?? 'uncommitted'})
                      </p>
                    )}

                    {/* Google-inspired Action History card embedded right inside bot/model replies */}
                    {msg.actionHistory && (
                      <ActionHistoryCard block={msg.actionHistory} defaultExpanded={true} />
                    )}
                  </article>
                );
              })
            )}
          </div>

          {/* Swarm Message Composer */}
          <form onSubmit={handleSubmit} className="border-t border-[#20242E] bg-[#11141A] p-4 space-y-3 rounded-b-xl">
            {composerError && (
              <p role="alert" className="text-[12.5px] text-red-400">
                {composerError}
              </p>
            )}

            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-4">
              <div>
                <label htmlFor="swarm-sender" className="sr-only">Sender agent</label>
                <select
                  id="swarm-sender"
                  value={senderAgentId}
                  onChange={(e) => setSenderAgentId(e.target.value)}
                  className="w-full rounded-lg border border-[#272C38] bg-[#14171D] px-2.5 py-1.5 text-[12.5px] text-[#E5E7EB]"
                >
                  {state.agents.map((a) => (
                    <option key={a.id} value={a.id}>
                      As: {a.displayName}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label htmlFor="swarm-target" className="sr-only">Target recipient</label>
                <select
                  id="swarm-target"
                  value={targetHandle}
                  onChange={(e) => setTargetHandle(e.target.value)}
                  className="w-full rounded-lg border border-[#272C38] bg-[#14171D] px-2.5 py-1.5 text-[12.5px] text-[#E5E7EB]"
                >
                  <option value="@all-agents">To: @all-agents</option>
                  {state.agents.map((a) => (
                    <option key={a.id} value={a.handle}>
                      To: {a.handle}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label htmlFor="swarm-kind" className="sr-only">Message protocol type</label>
                <select
                  id="swarm-kind"
                  value={messageKind}
                  onChange={(e) => setMessageKind(e.target.value as MessageKind)}
                  className="w-full rounded-lg border border-[#272C38] bg-[#14171D] px-2.5 py-1.5 text-[12.5px] text-[#E5E7EB]"
                >
                  <option value="handoff">Type: Handoff</option>
                  <option value="patch_ready">Type: Patch Ready</option>
                  <option value="conflict_alert">Type: Conflict Alert</option>
                  <option value="verification">Type: Verification</option>
                  <option value="devlog_sync">Type: Devlog Sync</option>
                  <option value="directive">Type: Directive</option>
                </select>
              </div>

              <div>
                <label htmlFor="swarm-ws" className="sr-only">Linked workstream</label>
                <select
                  id="swarm-ws"
                  value={workstreamId}
                  onChange={(e) => setWorkstreamId(e.target.value)}
                  className="w-full rounded-lg border border-[#272C38] bg-[#14171D] px-2.5 py-1.5 text-[12.5px] text-[#E5E7EB]"
                >
                  <option value="">No linked branch</option>
                  {state.workstreams.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.branch}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="flex flex-col gap-2.5 sm:flex-row sm:items-end">
              <div className="flex-1">
                <label htmlFor="swarm-body" className="sr-only">
                  Swarm message content
                </label>
                <textarea
                  id="swarm-body"
                  rows={2}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder={`Message #${activeChannel} or run /swarm claim <target>, /swarm room <channel>, /swarm focus ctf, /swarm status...`}
                  className="w-full rounded-lg border border-[#272C38] bg-[#14171D] px-3 py-2 text-[13.5px] text-[#F3F4F6] placeholder-[#6B7280] focus:border-blue-500 focus:outline-none"
                />
              </div>

              <button
                type="submit"
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2.5 text-[13px] font-medium text-white transition-colors hover:bg-blue-500 whitespace-nowrap shrink-0"
              >
                <Send className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Send to Swarm</span>
              </button>
            </div>

            <label className="inline-flex items-center gap-2 text-[12px] text-[#9CA3AF] cursor-pointer">
              <input
                type="checkbox"
                checked={syncToDevlog}
                onChange={(e) => setSyncToDevlog(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-[#363C4E] bg-[#0D0F13] accent-blue-500"
              />
              <span>Also append entry to shared DEVLOG.md ledger for cross-model continuity</span>
            </label>
          </form>
        </section>
      </div>
    </div>
  );
}
