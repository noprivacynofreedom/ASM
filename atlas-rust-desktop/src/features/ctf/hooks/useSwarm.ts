import { useCallback, useEffect, useRef, useState } from 'react';
import type { SwarmRoomState, UserProfile, WorkspaceView, ZipEntryItem } from '../types';

export type SwarmConnectionStatus = 'connected' | 'reconnecting' | 'disconnected';

const SWARM_API_BASE = 'http://127.0.0.1:8090/api/swarm';

function getInitialRoomId(): string {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get('room');
  if (fromUrl && /^[a-zA-Z0-9_-]{2,48}$/.test(fromUrl)) {
    return fromUrl.toLowerCase();
  }
  return 'atlas-alpha';
}

function getSessionId(): string {
  const key = 'atlas_swarm_session_id';
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = `sess_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
    sessionStorage.setItem(key, id);
  }
  return id;
}

export function useSwarm(options: {
  profile: UserProfile | null;
  activeView: WorkspaceView;
  activeChallengeId: string | null;
  onRemoteFocus?: (challengeId: string, fromHandle: string) => void;
}) {
  const { profile, activeView, activeChallengeId, onRemoteFocus } = options;
  const [roomId, setRoomId] = useState<string>(getInitialRoomId);
  const [status, setStatus] = useState<SwarmConnectionStatus>('disconnected');
  const [roomState, setRoomState] = useState<SwarmRoomState>({
    roomId: getInitialRoomId(),
    peers: [],
    claims: {},
    sharedNotes: {},
    archiveManifest: null,
    feed: [],
  });

  const sessionIdRef = useRef<string>(getSessionId());
  const lastFocusIdRef = useRef<string | null>(null);
  const channelRef = useRef<BroadcastChannel | null>(null);
  const onRemoteFocusRef = useRef(onRemoteFocus);
  onRemoteFocusRef.current = onRemoteFocus;

  const latestPresenceRef = useRef({
    activeView,
    activeChallengeId,
    handle: profile?.handle || 'guest',
    role: profile?.role || 'player',
    uid: profile?.uid || sessionIdRef.current,
  });

  latestPresenceRef.current = {
    activeView,
    activeChallengeId,
    handle: profile?.handle || 'guest',
    role: profile?.role || 'player',
    uid: profile?.uid || sessionIdRef.current,
  };

  const applySnapshot = useCallback((snap: SwarmRoomState & { lastFocus?: { id: string; challengeId: string; handle: string; sessionId: string } | null }) => {
    setRoomState({
      roomId: snap.roomId,
      peers: snap.peers || [],
      claims: snap.claims || {},
      sharedNotes: snap.sharedNotes || {},
      archiveManifest: snap.archiveManifest || null,
      feed: snap.feed || [],
    });
    if (
      snap.lastFocus &&
      snap.lastFocus.id &&
      snap.lastFocus.id !== lastFocusIdRef.current
    ) {
      lastFocusIdRef.current = snap.lastFocus.id;
      if (snap.lastFocus.sessionId !== sessionIdRef.current && onRemoteFocusRef.current) {
        onRemoteFocusRef.current(snap.lastFocus.challengeId, snap.lastFocus.handle || 'peer');
      }
    }
  }, []);

  const sendEvent = useCallback(
    async (payload: Record<string, unknown>, targetRoom = roomId) => {
      const p = latestPresenceRef.current;
      try {
        const res = await fetch(`${SWARM_API_BASE}/room/${encodeURIComponent(targetRoom)}/event`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sessionId: sessionIdRef.current,
            uid: p.uid,
            handle: p.handle,
            role: p.role,
            ...payload,
          }),
        });
        if (!res.ok) return;
        const snap = await res.json();
        setStatus('connected');
        applySnapshot(snap);
        channelRef.current?.postMessage({ type: 'swarm:sync', roomId: targetRoom, snap });
      } catch {
        setStatus('reconnecting');
      }
    },
    [roomId, applySnapshot]
  );

  useEffect(() => {
    if (!profile) {
      setStatus('disconnected');
      return;
    }

    let cancelled = false;
    const activeRoom = roomId;

    if (typeof BroadcastChannel !== 'undefined') {
      const bc = new BroadcastChannel(`atlas_ctf_swarm_${activeRoom}`);
      channelRef.current = bc;
      bc.onmessage = (ev) => {
        if (!cancelled && ev.data?.type === 'swarm:sync' && ev.data?.snap) {
          applySnapshot(ev.data.snap);
        }
      };
    }

    const p = latestPresenceRef.current;
    void sendEvent(
      {
        type: 'room:join',
        activeView: p.activeView,
        activeChallengeId: p.activeChallengeId,
      },
      activeRoom
    );

    const poll = async () => {
      if (cancelled || document.hidden) return;
      try {
        const res = await fetch(`${SWARM_API_BASE}/room/${encodeURIComponent(activeRoom)}`);
        if (!res.ok) {
          if (!cancelled) setStatus('reconnecting');
          return;
        }
        const snap = await res.json();
        if (!cancelled) {
          setStatus('connected');
          applySnapshot(snap);
        }
      } catch {
        if (!cancelled) setStatus('reconnecting');
      }
    };

    const timer = window.setInterval(() => void poll(), 2000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
      if (channelRef.current) {
        channelRef.current.close();
        channelRef.current = null;
      }
      void fetch(`${SWARM_API_BASE}/room/${encodeURIComponent(activeRoom)}/event`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: 'room:leave',
          sessionId: sessionIdRef.current,
        }),
      }).catch(() => {});
    };
  }, [profile?.uid, roomId, sendEvent, applySnapshot]);

  useEffect(() => {
    if (!profile) return;
    void sendEvent({
      type: 'presence:update',
      activeView,
      activeChallengeId,
      handle: profile.handle,
      role: profile.role,
    });
  }, [activeView, activeChallengeId, profile?.handle, profile?.role, sendEvent]);

  const joinRoom = useCallback((nextRoom: string) => {
    const cleaned = nextRoom.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '').slice(0, 48);
    if (cleaned.length < 2) return;
    const url = new URL(window.location.href);
    url.searchParams.set('room', cleaned);
    window.history.replaceState({}, '', url.toString());
    setRoomId(cleaned);
  }, []);

  const toggleClaim = useCallback(
    (challengeId: string) => {
      void sendEvent({ type: 'claim:toggle', challengeId });
    },
    [sendEvent]
  );

  const syncSharedNote = useCallback(
    (challengeId: string, content: string) => {
      void sendEvent({ type: 'note:sync', challengeId, content });
    },
    [sendEvent]
  );

  const shareArchiveManifest = useCallback(
    (fileName: string, entries: ZipEntryItem[]) => {
      const files = entries.filter((e) => !e.dir);
      void sendEvent({
        type: 'archive:share',
        fileName,
        fileCount: files.length,
        paths: files.slice(0, 120).map((e) => e.path),
      });
    },
    [sendEvent]
  );

  const announceFlag = useCallback(
    (challengeId: string, challengeTitle: string) => {
      void sendEvent({ type: 'flag:announce', challengeId, title: challengeTitle });
    },
    [sendEvent]
  );

  const broadcastFocus = useCallback(
    (challengeId: string) => {
      void sendEvent({ type: 'focus:broadcast', challengeId });
    },
    [sendEvent]
  );

  const sendMessage = useCallback(
    (rawText: string, challengeId?: string): string | null => {
      const text = rawText.trim();
      if (!text) return null;

      if (text.startsWith('/swarm')) {
        const parts = text.split(/\s+/);
        const cmd = (parts[1] || '').toLowerCase();
        const arg = parts.slice(2).join(' ').trim();

        if (cmd === 'room' && arg) {
          joinRoom(arg);
          return `Switched Swarm room to "${arg}".`;
        }
        if (cmd === 'claim' && arg) {
          toggleClaim(arg);
          return `Toggled Swarm claim on "${arg}".`;
        }
        if (cmd === 'focus' && arg) {
          broadcastFocus(arg);
          return `Broadcast focus directive for "${arg}".`;
        }
        if (cmd === 'help' || !cmd) {
          return 'Commands: /swarm room <name>, /swarm claim <challenge-id>, /swarm focus <challenge-id>, or type any message to broadcast.';
        }
      }

      void sendEvent({
        type: 'feed:post',
        text,
        challengeId,
      });
      return null;
    },
    [sendEvent, joinRoom, toggleClaim, broadcastFocus]
  );

  return {
    sessionId: sessionIdRef.current,
    roomId,
    status,
    roomState,
    joinRoom,
    toggleClaim,
    syncSharedNote,
    shareArchiveManifest,
    announceFlag,
    broadcastFocus,
    sendMessage,
  };
}
