import React, { useState } from 'react';
import {
  Check,
  Copy,
  FileArchive,
  Radio,
  Send,
  Target,
  Terminal,
  Users,
} from 'lucide-react';
import type { Challenge, SwarmRoomState } from '../types';
import type { SwarmConnectionStatus } from '../hooks/useSwarm';

interface Props {
  roomId: string;
  status: SwarmConnectionStatus;
  roomState: SwarmRoomState;
  mySessionId: string;
  challenges: Challenge[];
  onJoinRoom: (roomId: string) => void;
  onSendMessage: (text: string) => string | null;
  onJumpToChallenge: (challengeId: string) => void;
  onToggleClaim: (challengeId: string) => void;
}

export function SwarmView({
  roomId,
  status,
  roomState,
  mySessionId,
  challenges,
  onJoinRoom,
  onSendMessage,
  onJumpToChallenge,
  onToggleClaim,
}: Props) {
  const [roomInput, setRoomInput] = useState(roomId);
  const [messageInput, setMessageInput] = useState('');
  const [localHint, setLocalHint] = useState<string | null>(null);
  const [copiedLink, setCopiedLink] = useState(false);

  const handleRoomSwitch = (e: React.FormEvent) => {
    e.preventDefault();
    if (roomInput.trim().length >= 2) {
      onJoinRoom(roomInput.trim());
    }
  };

  const handleDispatch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!messageInput.trim()) return;
    const reply = onSendMessage(messageInput);
    setLocalHint(reply);
    setMessageInput('');
  };

  const copyInviteUrl = async () => {
    const url = new URL(window.location.href);
    url.searchParams.set('room', roomId);
    await navigator.clipboard.writeText(url.toString());
    setCopiedLink(true);
    window.setTimeout(() => setCopiedLink(false), 1800);
  };

  const claimsList = Object.values(roomState.claims);

  const statusMeta =
    status === 'connected'
      ? { dot: 'bg-emerald-500', label: 'Connected', text: 'text-emerald-600 dark:text-emerald-400' }
      : status === 'reconnecting'
      ? { dot: 'bg-amber-500', label: 'Reconnecting', text: 'text-amber-600 dark:text-amber-400' }
      : { dot: 'bg-slate-400', label: 'Disconnected', text: 'text-slate-500' };

  return (
    <div className="space-y-6">
      {/* Room Control Bar */}
      <div className="border border-slate-200 dark:border-slate-800 rounded-lg p-5 bg-white dark:bg-[#111827] flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5">
            <Radio className="w-4 h-4 text-amber-500" />
            <h2 className="text-base font-semibold font-display text-slate-900 dark:text-slate-100">
              Swarm Multi-Session Room: <span className="font-mono">{roomId}</span>
            </h2>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className={`inline-flex items-center gap-1.5 font-medium ${statusMeta.text}`}>
              <span className={`w-2 h-2 rounded-full ${statusMeta.dot}`} />
              {statusMeta.label}
            </span>
            <span aria-hidden="true">·</span>
            <span className="font-mono tabular-nums">
              {roomState.peers.length} active session{roomState.peers.length === 1 ? '' : 's'}
            </span>
            <span aria-hidden="true">·</span>
            <span>Open the room link in another tab or browser to collaborate live</span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <form onSubmit={handleRoomSwitch} className="flex items-center gap-2">
            <input
              type="text"
              value={roomInput}
              onChange={(e) => setRoomInput(e.target.value)}
              placeholder="Room ID..."
              className="w-40 px-3 py-1.5 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
            />
            <button
              type="submit"
              className="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer whitespace-nowrap"
            >
              Switch Room
            </button>
          </form>

          <button
            type="button"
            onClick={() => void copyInviteUrl()}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-md bg-amber-500 text-slate-950 hover:bg-amber-400 transition-colors cursor-pointer whitespace-nowrap"
          >
            {copiedLink ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            {copiedLink ? 'Invite Link Copied' : 'Copy Session Link'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Active Peers, Claims & Shared Archive Manifest */}
        <div className="lg:col-span-5 space-y-6">
          {/* Active Connected Sessions */}
          <div className="border border-slate-200 dark:border-slate-800 rounded-lg bg-white dark:bg-[#111827] overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Users className="w-4 h-4 text-slate-500" />
                <h3 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
                  Connected Sessions
                </h3>
              </div>
              <span className="text-xs font-mono tabular-nums text-slate-500">
                {roomState.peers.length} online
              </span>
            </div>

            <div className="divide-y divide-slate-100 dark:divide-slate-800/70">
              {roomState.peers.length === 0 ? (
                <div className="p-4 text-xs text-slate-500">Waiting for session presence...</div>
              ) : (
                roomState.peers.map((peer) => {
                  const isMe = peer.sessionId === mySessionId;
                  return (
                    <div
                      key={peer.sessionId}
                      className="px-4 py-3 flex items-center justify-between gap-3 text-xs"
                    >
                      <div className="min-w-0">
                        <p className="font-mono font-medium text-slate-900 dark:text-slate-100 truncate">
                          @{peer.handle} {isMe ? '(this session)' : ''}
                        </p>
                        <p className="text-slate-500 mt-0.5 truncate">
                          {peer.role} · view: {peer.activeView}
                          {peer.activeChallengeId ? ` · ${peer.activeChallengeId}` : ''}
                        </p>
                      </div>
                      <span className="shrink-0 font-mono tabular-nums text-[11px] text-slate-500">
                        {new Date(peer.joinedAt).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </span>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Active Challenge Claims */}
          <div className="border border-slate-200 dark:border-slate-800 rounded-lg bg-white dark:bg-[#111827] overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Target className="w-4 h-4 text-slate-500" />
                <h3 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
                  Target Claims
                </h3>
              </div>
              <span className="text-xs font-mono tabular-nums text-slate-500">
                {claimsList.length} active
              </span>
            </div>

            <div className="divide-y divide-slate-100 dark:divide-slate-800/70">
              {claimsList.length === 0 ? (
                <div className="p-4 text-xs text-slate-500">
                  No targets claimed yet. Claim a module from Curriculum or type{' '}
                  <span className="font-mono">/swarm claim nm-04-bof-variable</span>.
                </div>
              ) : (
                claimsList.map((claim) => {
                  const matched = challenges.find((c) => c.id === claim.challengeId);
                  return (
                    <div
                      key={claim.challengeId}
                      className="px-4 py-3 flex items-center justify-between gap-2 text-xs"
                    >
                      <div className="min-w-0">
                        <button
                          type="button"
                          onClick={() => onJumpToChallenge(claim.challengeId)}
                          className="font-medium text-slate-900 dark:text-slate-100 hover:text-amber-500 truncate block text-left cursor-pointer"
                        >
                          {matched ? `${matched.moduleNum}. ${matched.title}` : claim.challengeId}
                        </button>
                        <p className="text-slate-500 font-mono mt-0.5">
                          Assigned to @{claim.handle}
                        </p>
                      </div>
                      {claim.sessionId === mySessionId && (
                        <button
                          type="button"
                          onClick={() => onToggleClaim(claim.challengeId)}
                          className="text-xs text-slate-500 hover:text-red-500 cursor-pointer shrink-0"
                        >
                          Release
                        </button>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Synced Archive Manifest */}
          <div className="border border-slate-200 dark:border-slate-800 rounded-lg p-4 bg-white dark:bg-[#111827] space-y-2.5">
            <div className="flex items-center gap-2">
              <FileArchive className="w-4 h-4 text-slate-500" />
              <h3 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
                Synced Nightmare.zip Manifest
              </h3>
            </div>
            {roomState.archiveManifest ? (
              <div className="space-y-2">
                <p className="text-xs text-slate-600 dark:text-slate-400">
                  <span className="font-mono text-slate-900 dark:text-slate-100">
                    {roomState.archiveManifest.fileName}
                  </span>{' '}
                  · {roomState.archiveManifest.fileCount} files · shared by @
                  {roomState.archiveManifest.sharedBy}
                </p>
                <div className="max-h-36 overflow-y-auto rounded bg-slate-50 dark:bg-[#0B1120] border border-slate-200 dark:border-slate-800 p-2.5 font-mono text-[11px] text-slate-600 dark:text-slate-400 space-y-1">
                  {roomState.archiveManifest.paths.map((p) => (
                    <div key={p} className="truncate">
                      {p}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-500">
                No archive manifest synced yet. Open Archive Explorer and click "Sync Manifest to
                Swarm".
              </p>
            )}
          </div>
        </div>

        {/* Right Column: Live Swarm Dispatch & Slash Command Feed */}
        <div className="lg:col-span-7 border border-slate-200 dark:border-slate-800 rounded-lg bg-white dark:bg-[#111827] flex flex-col h-[580px]">
          <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Terminal className="w-4 h-4 text-amber-500" />
              <h3 className="text-sm font-semibold font-display text-slate-900 dark:text-slate-100">
                Swarm Command & Activity Feed
              </h3>
            </div>
            <span className="text-xs font-mono text-slate-500">
              Try /swarm help
            </span>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {roomState.feed.length === 0 ? (
              <div className="text-xs text-slate-500 py-8 text-center">
                No room messages yet. Broadcast findings or run{' '}
                <span className="font-mono">/swarm claim &lt;challenge-id&gt;</span>.
              </div>
            ) : (
              roomState.feed.map((ev) => (
                <div
                  key={ev.id}
                  className="text-xs border-b border-slate-100 dark:border-slate-800/70 pb-2.5 last:border-b-0"
                >
                  <div className="flex items-center justify-between gap-2 text-slate-500">
                    <span>
                      <span className="font-mono font-semibold text-slate-900 dark:text-slate-100">
                        @{ev.handle}
                      </span>{' '}
                      · {ev.role} · {ev.type}
                    </span>
                    <span className="font-mono tabular-nums text-[11px]">
                      {new Date(ev.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                  <p className="mt-1 text-slate-700 dark:text-slate-300 leading-relaxed break-words">
                    {ev.text}
                  </p>
                </div>
              ))
            )}
          </div>

          <div className="p-3.5 border-t border-slate-200 dark:border-slate-800 space-y-2">
            {localHint && (
              <p className="text-xs font-mono text-amber-600 dark:text-amber-400">{localHint}</p>
            )}
            <form onSubmit={handleDispatch} className="flex gap-2">
              <input
                type="text"
                value={messageInput}
                onChange={(e) => setMessageInput(e.target.value)}
                placeholder="Share an offset, note, or /swarm focus nm-04-bof-variable..."
                className="flex-1 px-3 py-2 text-xs font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
              />
              <button
                type="submit"
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-md bg-amber-500 text-slate-950 hover:bg-amber-400 transition-colors cursor-pointer whitespace-nowrap"
              >
                <Send className="w-3.5 h-3.5" />
                Send
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
