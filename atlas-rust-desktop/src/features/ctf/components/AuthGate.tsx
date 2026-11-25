import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  KeyRound,
  LogOut,
  Mail,
  RefreshCw,
  Shield,
  Terminal,
  UserPlus,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

export function AuthGate() {
  const {
    firebaseUser,
    profile,
    needsProfileSetup,
    authError,
    clearAuthError,
    loginWithGoogle,
    loginWithEmail,
    registerWithEmail,
    completeProfileSetup,
    logout,
    resendVerification,
    refreshUser,
  } = useAuth();

  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [handle, setHandle] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [teamName, setTeamName] = useState('');
  const [requestOrganizer, setRequestOrganizer] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [infoMsg, setInfoMsg] = useState<string | null>(null);

  useEffect(() => {
    if (firebaseUser && needsProfileSetup) {
      const saved = localStorage.getItem(`atlas_pending_reg_${firebaseUser.uid}`);
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          if (parsed.handle) setHandle(parsed.handle);
          if (parsed.displayName) setDisplayName(parsed.displayName);
          if (parsed.teamName) setTeamName(parsed.teamName);
          if (typeof parsed.requestOrganizer === 'boolean') {
            setRequestOrganizer(parsed.requestOrganizer);
          }
          return;
        } catch {
          // Ignore invalid cache
        }
      }
      const fallbackName = firebaseUser.displayName || firebaseUser.email?.split('@')[0] || '';
      setDisplayName(fallbackName);
      setHandle(
        fallbackName
          .toLowerCase()
          .replace(/[^a-z0-9_-]/g, '_')
          .slice(0, 24)
      );
    }
  }, [firebaseUser, needsProfileSetup]);

  const handleGoogle = async () => {
    setSubmitting(true);
    setInfoMsg(null);
    try {
      await loginWithGoogle();
    } catch {
      // Error surfaced via authError
    } finally {
      setSubmitting(false);
    }
  };

  const handleEmailSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setInfoMsg(null);
    try {
      if (mode === 'login') {
        await loginWithEmail(email, password);
      } else {
        const res = await registerWithEmail({
          email,
          password,
          handle: handle || email.split('@')[0],
          displayName: displayName || handle || email.split('@')[0],
          teamName,
          requestOrganizer,
        });
        if (res.verificationSent) {
          setInfoMsg(
            'Account created. Check your inbox to verify your email address, then click "Check Verification".'
          );
        }
      }
    } catch {
      // Handled in AuthContext
    } finally {
      setSubmitting(false);
    }
  };

  const handleCompleteOnboarding = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setInfoMsg(null);
    try {
      await completeProfileSetup({
        handle,
        displayName,
        teamName,
        requestOrganizer,
      });
    } catch (err) {
      setInfoMsg(err instanceof Error ? err.message : 'Unable to save profile.');
    } finally {
      setSubmitting(false);
    }
  };

  // Suspended Account Screen
  if (firebaseUser && profile?.status === 'suspended') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-[#0B1120] p-6">
        <div className="max-w-md w-full border border-slate-200 dark:border-slate-800 bg-white dark:bg-[#111827] rounded-lg p-6 space-y-4">
          <div className="flex items-center gap-3 text-red-600 dark:text-red-400">
            <AlertCircle className="w-5 h-5 shrink-0" />
            <h1 className="text-lg font-semibold font-display">Account Suspended</h1>
          </div>
          <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed">
            Operator handle <span className="font-mono font-medium">@{profile.handle}</span> is
            currently suspended by an Atlas CTF administrator. Contact your competition organizer to
            restore access.
          </p>
          <button
            type="button"
            onClick={() => void logout()}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </div>
    );
  }

  // Email Verification Gate for newly registered Email/Password accounts
  if (firebaseUser && !firebaseUser.emailVerified) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-[#0B1120] p-6">
        <div className="max-w-md w-full border border-slate-200 dark:border-slate-800 bg-white dark:bg-[#111827] rounded-lg p-6 space-y-5">
          <div className="space-y-1">
            <h1 className="text-xl font-semibold font-display text-slate-900 dark:text-slate-100">
              Verify Your Email Address
            </h1>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              Atlas CTF enforces verified email identities before enabling Firestore writes and
              Swarm sessions.
            </p>
          </div>
          <div className="text-sm text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-md p-3.5">
            Verification link sent to <span className="font-mono">{firebaseUser.email}</span>.
          </div>
          {infoMsg && (
            <p className="text-xs text-emerald-600 dark:text-emerald-400">{infoMsg}</p>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={async () => {
                await refreshUser();
                setInfoMsg('Checked verification status.');
              }}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md bg-amber-500 text-slate-950 hover:bg-amber-400 transition-colors cursor-pointer whitespace-nowrap"
            >
              <RefreshCw className="w-4 h-4" />
              Check Verification
            </button>
            <button
              type="button"
              onClick={async () => {
                await resendVerification();
                setInfoMsg('Verification email resent.');
              }}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer whitespace-nowrap"
            >
              <Mail className="w-4 h-4" />
              Resend Email
            </button>
            <button
              type="button"
              onClick={() => void logout()}
              className="ml-auto text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 cursor-pointer"
            >
              Sign Out
            </button>
          </div>
        </div>
      </div>
    );
  }

  // First-Time Registration Profile Setup
  if (firebaseUser && needsProfileSetup) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-[#0B1120] p-6">
        <div className="max-w-lg w-full border border-slate-200 dark:border-slate-800 bg-white dark:bg-[#111827] rounded-lg p-7 space-y-6">
          <div className="space-y-1.5">
            <p className="text-xs text-amber-600 dark:text-amber-400 font-medium">
              Operator Registration
            </p>
            <h1 className="text-2xl font-semibold font-display text-slate-900 dark:text-slate-100">
              Configure Your Atlas CTF Profile
            </h1>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              Choose your handle for the scoreboard and real-time Swarm sessions. Signed in as{' '}
              <span className="font-mono text-slate-800 dark:text-slate-200">
                {firebaseUser.email}
              </span>
              .
            </p>
          </div>

          <form onSubmit={handleCompleteOnboarding} className="space-y-4">
            <div className="space-y-1.5">
              <label
                htmlFor="reg-handle"
                className="block text-sm font-medium text-slate-700 dark:text-slate-300"
              >
                Operator Handle
              </label>
              <input
                id="reg-handle"
                type="text"
                required
                minLength={2}
                maxLength={32}
                pattern="^[a-zA-Z0-9_\-]+$"
                value={handle}
                onChange={(e) => setHandle(e.target.value)}
                placeholder="e.g. bin_analyst"
                className="w-full px-3.5 py-2 text-sm font-mono rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/50"
              />
              <p className="text-xs text-slate-500">
                2–32 characters: letters, numbers, underscores, or hyphens.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label
                  htmlFor="reg-display"
                  className="block text-sm font-medium text-slate-700 dark:text-slate-300"
                >
                  Display Name
                </label>
                <input
                  id="reg-display"
                  type="text"
                  required
                  maxLength={80}
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Alex Rivera"
                  className="w-full px-3.5 py-2 text-sm rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/50"
                />
              </div>

              <div className="space-y-1.5">
                <label
                  htmlFor="reg-team"
                  className="block text-sm font-medium text-slate-700 dark:text-slate-300"
                >
                  Team Name (Optional)
                </label>
                <input
                  id="reg-team"
                  type="text"
                  maxLength={64}
                  value={teamName}
                  onChange={(e) => setTeamName(e.target.value)}
                  placeholder="Binary Lab"
                  className="w-full px-3.5 py-2 text-sm rounded-md bg-slate-50 dark:bg-[#0B1120] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/50"
                />
              </div>
            </div>

            <label className="flex items-start gap-3 p-3.5 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-[#0B1120] cursor-pointer">
              <input
                type="checkbox"
                checked={requestOrganizer}
                onChange={(e) => setRequestOrganizer(e.target.checked)}
                className="mt-1 rounded border-slate-400 text-amber-500 focus:ring-amber-500"
              />
              <span className="text-sm text-slate-700 dark:text-slate-300">
                <span className="font-medium block">Request Organizer Role</span>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  New accounts start with Player permissions. Requesting Organizer flags your
                  account for an Administrator to grant Challenge Studio permissions.
                </span>
              </span>
            </label>

            {infoMsg && (
              <p className="text-xs text-red-600 dark:text-red-400">{infoMsg}</p>
            )}

            <div className="flex items-center justify-between pt-2">
              <button
                type="button"
                onClick={() => void logout()}
                className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 cursor-pointer"
              >
                Use Different Account
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold rounded-md bg-amber-500 text-slate-950 hover:bg-amber-400 disabled:opacity-50 transition-colors cursor-pointer whitespace-nowrap"
              >
                <CheckCircle2 className="w-4 h-4" />
                {submitting ? 'Saving Profile...' : 'Enter Atlas CTF'}
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  // Primary Unauthenticated Login / Register Portal
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-[#0B1120] flex flex-col lg:flex-row">
      {/* Left Architectural Column: Workbench Context */}
      <div className="lg:w-1/2 p-8 lg:p-14 flex flex-col justify-between border-b lg:border-b-0 lg:border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-[#0F172A]">
        <div className="space-y-8 max-w-xl">
          <div className="flex items-center gap-2.5 text-slate-900 dark:text-slate-100">
            <Terminal className="w-5 h-5 text-amber-500" />
            <span className="text-lg font-bold font-display tracking-tight">Atlas CTF</span>
          </div>

          <div className="space-y-4">
            <h1 className="text-3xl sm:text-4xl font-bold font-display tracking-tight text-slate-900 dark:text-slate-100 leading-tight [text-wrap:balance]">
              Nightmare Binary Analysis & Multi-Session CTF Workbench
            </h1>
            <p className="text-base text-slate-600 dark:text-slate-400 leading-relaxed">
              Import and inspect Nightmare.zip archives client-side, study ELF security mitigations
              and stack layouts, coordinate live across Swarm rooms, and manage competition
              challenges with strict role-based access control.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 pt-4 border-t border-slate-200 dark:border-slate-800">
            <div className="space-y-1">
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">Player</p>
              <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
                Solve Nightmare labs, inspect ELF binaries, verify flags, and join live Swarm rooms.
              </p>
            </div>
            <div className="space-y-1">
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">Organizer</p>
              <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
                Author, publish, and maintain CTF challenges, SHA-256 flags, and study modules.
              </p>
            </div>
            <div className="space-y-1">
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">Admin</p>
              <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
                Manage user roles, approve Organizer elevations, moderate accounts, and seed labs.
              </p>
            </div>
          </div>
        </div>

        <p className="text-xs text-slate-500 mt-10">
          Secured with Firebase Authentication, isolated PII storage, and role-enforced Firestore
          rules.
        </p>
      </div>

      {/* Right Authentication Form Column */}
      <div className="lg:w-1/2 flex items-center justify-center p-8 lg:p-14">
        <div className="w-full max-w-md space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold font-display text-slate-900 dark:text-slate-100">
              {mode === 'login' ? 'Sign In to Atlas CTF' : 'Register Operator Account'}
            </h2>
            <div className="flex items-center gap-1 p-1 rounded-md bg-slate-200/70 dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
              <button
                type="button"
                onClick={() => {
                  setMode('login');
                  clearAuthError();
                  setInfoMsg(null);
                }}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors cursor-pointer whitespace-nowrap ${
                  mode === 'login'
                    ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                Sign In
              </button>
              <button
                type="button"
                onClick={() => {
                  setMode('register');
                  clearAuthError();
                  setInfoMsg(null);
                }}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors cursor-pointer whitespace-nowrap ${
                  mode === 'register'
                    ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                Register
              </button>
            </div>
          </div>

          {/* Primary Google Sign-In */}
          <button
            type="button"
            disabled={submitting}
            onClick={handleGoogle}
            className="w-full flex items-center justify-center gap-2.5 px-4 py-2.5 text-sm font-semibold rounded-md bg-amber-500 text-slate-950 hover:bg-amber-400 disabled:opacity-50 transition-colors cursor-pointer"
          >
            <Shield className="w-4 h-4" />
            {mode === 'login' ? 'Continue with Google' : 'Register with Google'}
          </button>

          <div className="relative flex items-center py-1">
            <div className="flex-grow border-t border-slate-200 dark:border-slate-800" />
            <span className="shrink-0 mx-3 text-xs text-slate-500">or use email & password</span>
            <div className="flex-grow border-t border-slate-200 dark:border-slate-800" />
          </div>

          {authError && (
            <div className="p-3.5 rounded-md border border-red-300 dark:border-red-900/70 bg-red-50 dark:bg-red-950/30 text-xs text-red-700 dark:text-red-300 leading-relaxed flex gap-2.5">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{authError}</span>
            </div>
          )}

          {infoMsg && (
            <div className="p-3.5 rounded-md border border-emerald-300 dark:border-emerald-900/70 bg-emerald-50 dark:bg-emerald-950/30 text-xs text-emerald-700 dark:text-emerald-300 leading-relaxed">
              {infoMsg}
            </div>
          )}

          <form onSubmit={handleEmailSubmit} className="space-y-4">
            {mode === 'register' && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                <div className="space-y-1">
                  <label
                    htmlFor="auth-handle"
                    className="block text-xs font-medium text-slate-700 dark:text-slate-300"
                  >
                    Handle
                  </label>
                  <input
                    id="auth-handle"
                    type="text"
                    required
                    minLength={2}
                    maxLength={32}
                    pattern="^[a-zA-Z0-9_\-]+$"
                    value={handle}
                    onChange={(e) => setHandle(e.target.value)}
                    placeholder="zero_day"
                    className="w-full px-3 py-2 text-sm font-mono rounded-md bg-white dark:bg-[#111827] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
                  />
                </div>
                <div className="space-y-1">
                  <label
                    htmlFor="auth-team"
                    className="block text-xs font-medium text-slate-700 dark:text-slate-300"
                  >
                    Team (Optional)
                  </label>
                  <input
                    id="auth-team"
                    type="text"
                    maxLength={64}
                    value={teamName}
                    onChange={(e) => setTeamName(e.target.value)}
                    placeholder="Atlas Unit"
                    className="w-full px-3 py-2 text-sm rounded-md bg-white dark:bg-[#111827] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
                  />
                </div>
              </div>
            )}

            <div className="space-y-1">
              <label
                htmlFor="auth-email"
                className="block text-xs font-medium text-slate-700 dark:text-slate-300"
              >
                Email Address
              </label>
              <input
                id="auth-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="operator@example.com"
                className="w-full px-3 py-2 text-sm rounded-md bg-white dark:bg-[#111827] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="auth-password"
                className="block text-xs font-medium text-slate-700 dark:text-slate-300"
              >
                Password
              </label>
              <input
                id="auth-password"
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Minimum 6 characters"
                className="w-full px-3 py-2 text-sm rounded-md bg-white dark:bg-[#111827] border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
              />
            </div>

            {mode === 'register' && (
              <label className="flex items-start gap-2.5 text-xs text-slate-600 dark:text-slate-400 cursor-pointer pt-1">
                <input
                  type="checkbox"
                  checked={requestOrganizer}
                  onChange={(e) => setRequestOrganizer(e.target.checked)}
                  className="mt-0.5 rounded border-slate-400 text-amber-500"
                />
                <span>
                  Request Organizer role (requires administrator approval after registration)
                </span>
              </label>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-[#111827] text-slate-900 dark:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors cursor-pointer"
            >
              {mode === 'login' ? (
                <>
                  <KeyRound className="w-4 h-4" />
                  {submitting ? 'Signing In...' : 'Sign In with Email'}
                </>
              ) : (
                <>
                  <UserPlus className="w-4 h-4" />
                  {submitting ? 'Creating Account...' : 'Create Account'}
                </>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
