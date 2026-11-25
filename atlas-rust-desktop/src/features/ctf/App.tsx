import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  collection,
  deleteDoc,
  doc,
  onSnapshot,
  query,
  serverTimestamp,
  setDoc,
  updateDoc,
  where,
} from 'firebase/firestore';
import {
  LogOut,
  Moon,
  Sun,
  Upload,
} from 'lucide-react';
import { db, handleFirestoreError, OperationType } from './firebase';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { ErrorBoundary } from './components/ErrorBoundary';
import { AuthGate } from './components/AuthGate';
import { CurriculumView } from './components/CurriculumView';
import { ArchiveExplorerView } from './components/ArchiveExplorerView';
import { ToolingLabView } from './components/ToolingLabView';
import { SwarmView } from './components/SwarmView';
import { AdminOrganizerView } from './components/AdminOrganizerView';
import { NIGHTMARE_SEED_CHALLENGES } from './data/nightmareModules';
import { useSwarm } from './hooks/useSwarm';
import { buildStarterNightmareZip, parseZipBlob } from './utils/ctfUtils';
import type {
  Challenge,
  UserProfile,
  UserProgress,
  UserRole,
  WorkspaceView,
  ZipEntryItem,
} from './types';

function AtlasWorkbench() {
  const { firebaseUser, profile, loading, needsProfileSetup, logout } = useAuth();

  const [darkMode, setDarkMode] = useState(true);
  const [activeView, setActiveView] = useState<WorkspaceView>('curriculum');
  const [selectedChallengeId, setSelectedChallengeId] = useState<string | null>(
    NIGHTMARE_SEED_CHALLENGES[0].id
  );

  // Nightmare.zip client archive state
  const [archiveName, setArchiveName] = useState('Nightmare.zip (Starter Edition)');
  const [archiveBlob, setArchiveBlob] = useState<Blob | null>(null);
  const [archiveEntries, setArchiveEntries] = useState<ZipEntryItem[]>([]);
  const [selectedZipPath, setSelectedZipPath] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Firestore synced state
  const [cloudChallenges, setCloudChallenges] = useState<Challenge[]>([]);
  const [myProgressMap, setMyProgressMap] = useState<Record<string, UserProgress>>({});
  const [allSolvedProgress, setAllSolvedProgress] = useState<UserProgress[]>([]);
  const [allUsers, setAllUsers] = useState<UserProfile[]>([]);
  const [focusBanner, setFocusBanner] = useState<string | null>(null);

  // Sync HTML .dark class cleanly
  useEffect(() => {
    const root = document.documentElement;
    if (darkMode) root.classList.add('dark');
    else root.classList.remove('dark');
  }, [darkMode]);

  // Load built-in starter Nightmare.zip on mount
  const loadStarterArchive = useCallback(async () => {
    const { blob, entries } = await buildStarterNightmareZip();
    setArchiveName('Nightmare.zip (Starter Edition)');
    setArchiveBlob(blob);
    setArchiveEntries(entries);
    const firstBin = entries.find((e) => e.isElf) || entries.find((e) => !e.dir);
    setSelectedZipPath(firstBin?.path ?? null);
  }, []);

  useEffect(() => {
    void loadStarterArchive();
  }, [loadStarterArchive]);

  // Real-time /swarm WebSocket hook
  const swarm = useSwarm({
    profile: profile && profile.status === 'active' ? profile : null,
    activeView,
    activeChallengeId: selectedChallengeId,
    onRemoteFocus: (challengeId, fromHandle) => {
      setSelectedChallengeId(challengeId);
      setActiveView('curriculum');
      setFocusBanner(`@${fromHandle} focused Swarm on ${challengeId}`);
      window.setTimeout(() => setFocusBanner(null), 5000);
    },
  });

  // Subscribe to Firestore challenges (only when authenticated & active)
  useEffect(() => {
    if (!firebaseUser || !profile || profile.status !== 'active') return;

    const bootstrapAdminEmail = (import.meta.env.VITE_ATLAS_BOOTSTRAP_ADMIN_EMAIL || '').toLowerCase();
    const isBootstrapAdmin =
      !!bootstrapAdminEmail &&
      firebaseUser.email?.toLowerCase() === bootstrapAdminEmail &&
      firebaseUser.emailVerified;

    const q = isBootstrapAdmin
      ? query(collection(db, 'challenges'))
      : query(collection(db, 'challenges'), where('published', '==', true));

    const unsub = onSnapshot(
      q,
      (snap) => {
        const list = snap.docs.map((d) => d.data() as Challenge);
        setCloudChallenges(list);
      },
      (error) => {
        handleFirestoreError(error, OperationType.LIST, 'challenges');
      }
    );

    // Organizers also subscribe to their own draft challenges
    let unsubOwnDrafts: (() => void) | null = null;
    if (profile.role === 'organizer' && !isBootstrapAdmin) {
      const ownQ = query(
        collection(db, 'challenges'),
        where('authorUid', '==', firebaseUser.uid)
      );
      unsubOwnDrafts = onSnapshot(
        ownQ,
        (snap) => {
          const ownList = snap.docs.map((d) => d.data() as Challenge);
          setCloudChallenges((prev) => {
            const map = new Map<string, Challenge>();
            for (const c of prev) map.set(c.id, c);
            for (const c of ownList) map.set(c.id, c);
            return Array.from(map.values());
          });
        },
        (error) => {
          handleFirestoreError(error, OperationType.LIST, 'challenges');
        }
      );
    }

    return () => {
      unsub();
      if (unsubOwnDrafts) unsubOwnDrafts();
    };
  }, [firebaseUser?.uid, profile?.role, profile?.status]);

  // Subscribe to user's own progress
  useEffect(() => {
    if (!firebaseUser || !profile || profile.status !== 'active') return;

    const q = query(
      collection(db, 'progress'),
      where('uid', '==', firebaseUser.uid)
    );
    const unsub = onSnapshot(
      q,
      (snap) => {
        const map: Record<string, UserProgress> = {};
        for (const d of snap.docs) {
          const item = { id: d.id, ...(d.data() as Omit<UserProgress, 'id'>) };
          map[item.challengeId] = item;
        }
        setMyProgressMap(map);
      },
      (error) => {
        handleFirestoreError(error, OperationType.LIST, 'progress');
      }
    );
    return () => unsub();
  }, [firebaseUser?.uid, profile?.status]);

  // Subscribe to verified solved scoreboard entries
  useEffect(() => {
    if (!firebaseUser || !profile || profile.status !== 'active') return;

    const q = query(collection(db, 'progress'), where('status', '==', 'solved'));
    const unsub = onSnapshot(
      q,
      (snap) => {
        setAllSolvedProgress(
          snap.docs.map((d) => ({
            id: d.id,
            ...(d.data() as Omit<UserProgress, 'id'>),
          }))
        );
      },
      (error) => {
        handleFirestoreError(error, OperationType.LIST, 'progress');
      }
    );
    return () => unsub();
  }, [firebaseUser?.uid, profile?.status]);

  // Subscribe to users list for Admin panel
  useEffect(() => {
    if (!firebaseUser || !profile || profile.role !== 'admin') return;

    const bootstrapAdminEmail = (import.meta.env.VITE_ATLAS_BOOTSTRAP_ADMIN_EMAIL || '').toLowerCase();
    const isBootstrapAdmin =
      !!bootstrapAdminEmail &&
      firebaseUser.email?.toLowerCase() === bootstrapAdminEmail &&
      firebaseUser.emailVerified;

    const q = isBootstrapAdmin
      ? query(collection(db, 'users'))
      : query(collection(db, 'users'), where('status', '==', 'active'));

    const unsub = onSnapshot(
      q,
      (snap) => {
        setAllUsers(snap.docs.map((d) => d.data() as UserProfile));
      },
      (error) => {
        handleFirestoreError(error, OperationType.LIST, 'users');
      }
    );
    return () => unsub();
  }, [firebaseUser?.uid, profile?.role]);

  // Merge cloud challenges with built-in Nightmare syllabus seeds (cloud takes precedence)
  const firestoreChallengeIds = useMemo(
    () => new Set(cloudChallenges.map((c) => c.id)),
    [cloudChallenges]
  );

  const mergedChallenges = useMemo(() => {
    const map = new Map<string, Challenge>();
    for (const seed of NIGHTMARE_SEED_CHALLENGES) {
      map.set(seed.id, seed);
    }
    for (const cloud of cloudChallenges) {
      const seedPreset = NIGHTMARE_SEED_CHALLENGES.find((s) => s.id === cloud.id)?.stackPreset;
      map.set(cloud.id, { ...cloud, stackPreset: seedPreset });
    }
    return Array.from(map.values()).sort((a, b) =>
      a.moduleNum.localeCompare(b.moduleNum, undefined, { numeric: true })
    );
  }, [cloudChallenges]);

  const handleImportZipFile = async (file: File) => {
    const entries = await parseZipBlob(file);
    setArchiveName(file.name);
    setArchiveBlob(file);
    setArchiveEntries(entries);
    const firstFile = entries.find((e) => e.isElf) || entries.find((e) => !e.dir);
    setSelectedZipPath(firstFile?.path ?? null);
    setActiveView('archive');
  };

  const handleDownloadCurrentArchive = () => {
    if (!archiveBlob) return;
    const url = URL.createObjectURL(archiveBlob);
    const a = document.createElement('a');
    a.href = url;
    a.download = archiveName.endsWith('.zip') ? archiveName : 'Nightmare.zip';
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleOpenArchivePath = (zipPath: string) => {
    const exact = archiveEntries.find((e) => e.path === zipPath);
    if (exact) {
      setSelectedZipPath(exact.path);
    } else {
      const fileName = zipPath.split('/').pop() || '';
      const fuzzy = archiveEntries.find((e) => !e.dir && e.path.endsWith(fileName));
      if (fuzzy) setSelectedZipPath(fuzzy.path);
    }
    setActiveView('archive');
  };

  const handleSaveProgress = async (params: {
    challenge: Challenge;
    status: 'unsolved' | 'in_progress' | 'solved';
    notes: string;
    pointsEarned: number;
  }) => {
    if (!firebaseUser || !profile) return;
    const docId = `${firebaseUser.uid}_${params.challenge.id}`.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 128);
    const existing = myProgressMap[params.challenge.id];
    const path = `progress/${docId}`;

    try {
      if (!existing) {
        await setDoc(doc(db, 'progress', docId), {
          uid: firebaseUser.uid,
          handle: profile.handle,
          challengeId: params.challenge.id,
          status: params.status,
          notes: params.notes.slice(0, 4000),
          pointsEarned: params.pointsEarned,
          createdAt: serverTimestamp(),
          updatedAt: serverTimestamp(),
        });
      } else if (existing.status === 'solved' && profile.role !== 'admin') {
        // Terminal state rule: only notes/handle/updatedAt change once solved
        await updateDoc(doc(db, 'progress', docId), {
          handle: profile.handle,
          notes: params.notes.slice(0, 4000),
          updatedAt: serverTimestamp(),
        });
      } else {
        await updateDoc(doc(db, 'progress', docId), {
          handle: profile.handle,
          status: params.status,
          notes: params.notes.slice(0, 4000),
          pointsEarned: params.pointsEarned,
          updatedAt: serverTimestamp(),
        });
      }
    } catch (error) {
      handleFirestoreError(error, existing ? OperationType.UPDATE : OperationType.CREATE, path);
    }
  };

  const handleSaveChallenge = async (
    challengeData: Omit<
      Challenge,
      'createdAt' | 'updatedAt' | 'authorUid' | 'stackPreset' | 'sampleFlag'
    >,
    isUpdate: boolean
  ) => {
    if (!firebaseUser) return;
    const path = `challenges/${challengeData.id}`;
    try {
      if (isUpdate) {
        await updateDoc(doc(db, 'challenges', challengeData.id), {
          moduleNum: challengeData.moduleNum,
          moduleName: challengeData.moduleName,
          title: challengeData.title,
          category: challengeData.category,
          difficulty: challengeData.difficulty,
          arch: challengeData.arch,
          points: challengeData.points,
          summary: challengeData.summary,
          objective: challengeData.objective,
          zipPath: challengeData.zipPath,
          flagHash: challengeData.flagHash,
          flagHint: challengeData.flagHint,
          published: challengeData.published,
          mitigations: challengeData.mitigations,
          exploitTemplate: challengeData.exploitTemplate,
          updatedAt: serverTimestamp(),
        });
      } else {
        await setDoc(doc(db, 'challenges', challengeData.id), {
          ...challengeData,
          authorUid: firebaseUser.uid,
          createdAt: serverTimestamp(),
          updatedAt: serverTimestamp(),
        });
      }
    } catch (error) {
      handleFirestoreError(error, isUpdate ? OperationType.UPDATE : OperationType.CREATE, path);
    }
  };

  const handleDeleteChallenge = async (challengeId: string) => {
    const path = `challenges/${challengeId}`;
    try {
      await deleteDoc(doc(db, 'challenges', challengeId));
    } catch (error) {
      handleFirestoreError(error, OperationType.DELETE, path);
    }
  };

  const handleSeedNightmareModules = async () => {
    if (!firebaseUser) return;
    for (const seed of NIGHTMARE_SEED_CHALLENGES) {
      if (firestoreChallengeIds.has(seed.id)) continue;
      const { stackPreset: _sp, sampleFlag: _sf, ...clean } = seed;
      await handleSaveChallenge(clean, false);
    }
  };

  const handleUpdateUserRole = async (targetUser: UserProfile, nextRole: UserRole) => {
    if (!firebaseUser) return;
    const userPath = `users/${targetUser.uid}`;
    try {
      await updateDoc(doc(db, 'users', targetUser.uid), {
        role: nextRole,
        requestedRole: 'none',
        updatedAt: serverTimestamp(),
      });
    } catch (error) {
      handleFirestoreError(error, OperationType.UPDATE, userPath);
    }

    // Keep trusted /admins and /organizers RBAC registries in lockstep
    const adminRef = doc(db, 'admins', targetUser.uid);
    const orgRef = doc(db, 'organizers', targetUser.uid);

    try {
      if (nextRole === 'admin') {
        await setDoc(adminRef, {
          uid: targetUser.uid,
          grantedBy: firebaseUser.uid,
          createdAt: serverTimestamp(),
        });
        await deleteDoc(orgRef).catch(() => {});
      } else if (nextRole === 'organizer') {
        await setDoc(orgRef, {
          uid: targetUser.uid,
          grantedBy: firebaseUser.uid,
          createdAt: serverTimestamp(),
        });
        await deleteDoc(adminRef).catch(() => {});
      } else {
        await deleteDoc(adminRef).catch(() => {});
        await deleteDoc(orgRef).catch(() => {});
      }
    } catch (error) {
      handleFirestoreError(error, OperationType.WRITE, `roles/${targetUser.uid}`);
    }
  };

  const handleToggleUserStatus = async (targetUser: UserProfile) => {
    const nextStatus = targetUser.status === 'active' ? 'suspended' : 'active';
    const path = `users/${targetUser.uid}`;
    try {
      await updateDoc(doc(db, 'users', targetUser.uid), {
        status: nextStatus,
        updatedAt: serverTimestamp(),
      });
    } catch (error) {
      handleFirestoreError(error, OperationType.UPDATE, path);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-[#0B1120] text-sm text-slate-500">
        Initializing Atlas CTF workbench...
      </div>
    );
  }

  if (!firebaseUser || needsProfileSetup || !profile || profile.status === 'suspended' || !firebaseUser.emailVerified) {
    return <AuthGate />;
  }

  const totalPoints = Object.values(myProgressMap)
    .filter((p) => p.status === 'solved')
    .reduce((sum, p) => sum + p.pointsEarned, 0);

  const navItems: Array<{ id: WorkspaceView; label: string }> = [
    { id: 'curriculum', label: 'Curriculum' },
    { id: 'archive', label: 'Archive' },
    { id: 'tooling', label: 'Tooling' },
    { id: 'swarm', label: 'Swarm' },
    {
      id: 'admin',
      label:
        profile.role === 'admin'
          ? 'Admin'
          : profile.role === 'organizer'
          ? 'Studio'
          : 'Standings',
    },
  ];

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 dark:bg-[#0B1120] text-slate-900 dark:text-slate-100">
      {/* Hidden Global Zip Input triggered by Primary Top-Bar CTA */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".zip"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void handleImportZipFile(f);
          e.target.value = '';
        }}
      />

      {/* Strict 3-Zone Top Bar Contract */}
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-[#0F172A]/95 backdrop-blur-sm">
        <div className="max-w-[1440px] mx-auto px-6 h-16 flex items-center justify-between gap-8">
          {/* Zone 1: Single-element Brand Wordmark */}
          <button
            type="button"
            onClick={() => setActiveView('curriculum')}
            className="text-lg font-bold font-display tracking-tight text-slate-900 dark:text-slate-100 whitespace-nowrap shrink-0 cursor-pointer"
          >
            Atlas CTF
          </button>

          {/* Zone 2: 5 Clean Single-Line Navigation Links */}
          <nav className="flex items-center gap-6 overflow-x-auto">
            {navItems.map((item) => {
              const active = activeView === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveView(item.id)}
                  className={`text-sm font-medium transition-colors whitespace-nowrap shrink-0 pb-0.5 cursor-pointer ${
                    active
                      ? 'text-slate-950 dark:text-amber-400 border-b-2 border-amber-500'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100'
                  }`}
                >
                  {item.label}
                </button>
              );
            })}
          </nav>

          {/* Zone 3: 1 Primary Action Button */}
          <div className="shrink-0">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-md bg-amber-500 text-slate-950 hover:bg-amber-400 transition-colors cursor-pointer whitespace-nowrap shrink-0"
            >
              <Upload className="w-3.5 h-3.5" />
              Import Nightmare.zip
            </button>
          </div>
        </div>
      </header>

      {/* Contextual Workspace Strip (below top bar) */}
      <div className="border-b border-slate-200 dark:border-slate-800 bg-slate-100/70 dark:bg-[#0D1426]">
        <div className="max-w-[1440px] mx-auto px-6 py-2.5 flex flex-wrap items-center justify-between gap-4 text-xs">
          <div className="flex flex-wrap items-center gap-2 text-slate-600 dark:text-slate-400">
            <span className="font-mono font-medium text-slate-900 dark:text-slate-100">
              @{profile.handle}
            </span>
            <span aria-hidden="true">·</span>
            <span className="capitalize">{profile.role}</span>
            {profile.teamName && (
              <>
                <span aria-hidden="true">·</span>
                <span>{profile.teamName}</span>
              </>
            )}
            <span aria-hidden="true">·</span>
            <span className="font-mono tabular-nums text-amber-600 dark:text-amber-400">
              {totalPoints} pts
            </span>
            <span aria-hidden="true">·</span>
            <button
              type="button"
              onClick={() => setActiveView('swarm')}
              className="inline-flex items-center gap-1.5 hover:text-slate-900 dark:hover:text-slate-100 cursor-pointer"
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  swarm.status === 'connected'
                    ? 'bg-emerald-500'
                    : swarm.status === 'reconnecting'
                    ? 'bg-amber-500'
                    : 'bg-slate-400'
                }`}
              />
              <span>
                Swarm {swarm.roomId} ({swarm.roomState.peers.length}{' '}
                {swarm.roomState.peers.length === 1 ? 'session' : 'sessions'} · {swarm.status})
              </span>
            </button>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setDarkMode((d) => !d)}
              className="inline-flex items-center gap-1.5 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 cursor-pointer whitespace-nowrap"
            >
              {darkMode ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
              {darkMode ? 'Light' : 'Dark'}
            </button>
            <span aria-hidden="true" className="text-slate-300 dark:text-slate-700">
              |
            </span>
            <button
              type="button"
              onClick={() => void logout()}
              className="inline-flex items-center gap-1.5 text-slate-600 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 cursor-pointer whitespace-nowrap"
            >
              <LogOut className="w-3.5 h-3.5" />
              Sign Out
            </button>
          </div>
        </div>
      </div>

      {focusBanner && (
        <div className="bg-amber-500/10 border-b border-amber-500/30 text-amber-700 dark:text-amber-300 text-xs py-2 px-6 text-center font-mono">
          {focusBanner}
        </div>
      )}

      {/* Main Content Canvas */}
      <main className="flex-1 max-w-[1440px] w-full mx-auto px-6 py-6">
        {activeView === 'curriculum' && (
          <CurriculumView
            challenges={mergedChallenges}
            selectedChallengeId={selectedChallengeId}
            onSelectChallenge={setSelectedChallengeId}
            progressMap={myProgressMap}
            onSaveProgress={handleSaveProgress}
            onOpenArchivePath={handleOpenArchivePath}
            swarmClaims={swarm.roomState.claims}
            swarmSharedNotes={swarm.roomState.sharedNotes}
            mySessionId={swarm.sessionId}
            onToggleSwarmClaim={swarm.toggleClaim}
            onSyncSwarmNote={swarm.syncSharedNote}
            onBroadcastFocus={swarm.broadcastFocus}
            onAnnounceFlag={swarm.announceFlag}
          />
        )}

        {activeView === 'archive' && (
          <ArchiveExplorerView
            archiveName={archiveName}
            entries={archiveEntries}
            selectedPath={selectedZipPath}
            onSelectPath={setSelectedZipPath}
            onImportZipFile={handleImportZipFile}
            onLoadStarterArchive={loadStarterArchive}
            onDownloadCurrentArchive={handleDownloadCurrentArchive}
            onSyncManifestToSwarm={() =>
              swarm.shareArchiveManifest(archiveName, archiveEntries)
            }
            swarmManifest={swarm.roomState.archiveManifest}
          />
        )}

        {activeView === 'tooling' && <ToolingLabView />}

        {activeView === 'swarm' && (
          <SwarmView
            roomId={swarm.roomId}
            status={swarm.status}
            roomState={swarm.roomState}
            mySessionId={swarm.sessionId}
            challenges={mergedChallenges}
            onJoinRoom={swarm.joinRoom}
            onSendMessage={swarm.sendMessage}
            onJumpToChallenge={(cid) => {
              setSelectedChallengeId(cid);
              setActiveView('curriculum');
            }}
            onToggleClaim={swarm.toggleClaim}
          />
        )}

        {activeView === 'admin' && (
          <AdminOrganizerView
            currentUser={profile}
            challenges={mergedChallenges}
            firestoreChallengeIds={firestoreChallengeIds}
            allUsers={allUsers}
            allSolvedProgress={allSolvedProgress}
            onSaveChallenge={handleSaveChallenge}
            onDeleteChallenge={handleDeleteChallenge}
            onSeedNightmareModules={handleSeedNightmareModules}
            onUpdateUserRole={handleUpdateUserRole}
            onToggleUserStatus={handleToggleUserStatus}
          />
        )}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <AtlasWorkbench />
      </AuthProvider>
    </ErrorBoundary>
  );
}
