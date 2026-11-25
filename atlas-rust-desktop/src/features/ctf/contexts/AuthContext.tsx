import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import {
  User,
  onAuthStateChanged,
  signInWithPopup,
  signInWithRedirect,
  getRedirectResult,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  sendEmailVerification,
  signOut,
  updateProfile,
  GoogleAuthProvider,
  signInWithCredential,
} from 'firebase/auth';
import { doc, getDoc, onSnapshot, serverTimestamp, setDoc, updateDoc } from 'firebase/firestore';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { auth, db, googleProvider, handleFirestoreError, OperationType } from '../firebase';
import type { RequestedRole, UserProfile } from '../types';

// Build-time configurable so no personal email ships in source (see .env.example).
const BOOTSTRAP_ADMIN_EMAIL = (import.meta.env.VITE_ATLAS_BOOTSTRAP_ADMIN_EMAIL || '').toLowerCase();

function sanitizeHandle(raw: string): string {
  const cleaned = raw
    .trim()
    .replace(/[^a-zA-Z0-9_-]/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 32);
  return cleaned.length >= 2 ? cleaned : `op_${Math.random().toString(36).slice(2, 7)}`;
}

interface AuthContextValue {
  firebaseUser: User | null;
  profile: UserProfile | null;
  loading: boolean;
  needsProfileSetup: boolean;
  authError: string | null;
  clearAuthError: () => void;
  loginWithGoogle: () => Promise<void>;
  loginWithEmail: (email: string, password: string) => Promise<void>;
  registerWithEmail: (params: {
    email: string;
    password: string;
    handle: string;
    displayName: string;
    teamName: string;
    requestOrganizer: boolean;
  }) => Promise<{ verificationSent: boolean }>;
  completeProfileSetup: (params: {
    handle: string;
    displayName: string;
    teamName: string;
    requestOrganizer: boolean;
  }) => Promise<void>;
  updateMyProfile: (params: {
    handle: string;
    displayName: string;
    teamName: string;
    requestedRole: RequestedRole;
  }) => Promise<void>;
  logout: () => Promise<void>;
  resendVerification: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

function base64UrlEncode(buffer: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buffer)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

async function generatePkce() {
  const randomBytes = crypto.getRandomValues(new Uint8Array(32));
  const verifier = base64UrlEncode(randomBytes.buffer);
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  const challenge = base64UrlEncode(digest);
  return { verifier, challenge };
}

async function signInWithGoogleTauri(): Promise<void> {
  const clientId = import.meta.env.VITE_GOOGLE_DESKTOP_CLIENT_ID;
  const clientSecret = import.meta.env.VITE_GOOGLE_DESKTOP_CLIENT_SECRET;
  const { verifier, challenge } = await generatePkce();
  const state = crypto.randomUUID();

  let timeout: ReturnType<typeof setTimeout>;
  let resolveCallback!: (url: string) => void;
  let rejectCallback!: (err: Error) => void;

  const callbackPromise = new Promise<string>((resolve, reject) => {
    resolveCallback = resolve;
    rejectCallback = reject;
  });

  const unlisten = await listen<string>('google-oauth-callback', (event) => {
    clearTimeout(timeout);
    unlisten();
    resolveCallback(event.payload);
  });

  timeout = setTimeout(() => {
    unlisten();
    rejectCallback(new Error('Google sign-in timed out after 3 minutes.'));
  }, 180_000);


  const authUrl = new URL('https://accounts.google.com/o/oauth2/v2/auth');
  authUrl.searchParams.set('client_id', clientId);
  authUrl.searchParams.set('redirect_uri', 'http://127.0.0.1:__PORT__');
  authUrl.searchParams.set('response_type', 'code');
  authUrl.searchParams.set('scope', 'openid email profile');
  authUrl.searchParams.set('code_challenge', challenge);
  authUrl.searchParams.set('code_challenge_method', 'S256');
  authUrl.searchParams.set('state', state);
  authUrl.searchParams.set('prompt', 'select_account');

  const port = await invoke<number>('start_google_oauth', {
    authUrl: authUrl.toString(),
  });

  const callbackUrl = new URL(await callbackPromise);
  const error = callbackUrl.searchParams.get('error');
  const code = callbackUrl.searchParams.get('code');

  if (error) throw new Error(`Google OAuth error: ${error}`);
  if (callbackUrl.searchParams.get('state') !== state) throw new Error('OAuth state mismatch.');
  if (!code) throw new Error('No authorization code returned from Google.');

  const tokens = await invoke<{ id_token: string; access_token: string }>(
    'exchange_google_code',
    {
      code,
      codeVerifier: verifier,
      redirectUri: `http://127.0.0.1:${port}`,
      clientId,
      clientSecret,
    }
  );

  const credential = GoogleAuthProvider.credential(tokens.id_token);
  await signInWithCredential(auth, credential);
}


const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [firebaseUser, setFirebaseUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [needsProfileSetup, setNeedsProfileSetup] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  const clearAuthError = useCallback(() => setAuthError(null), []);

  useEffect(() => {
    let unsubProfile: (() => void) | null = null;

    // Complete pending redirect sign-in (used when WebView2 blocks OAuth popups)
    getRedirectResult(auth).catch((error) => {
      const code = (error as { code?: string })?.code || '';
      if (code === 'auth/unauthorized-domain') {
        setAuthError(
          `Google Sign-In redirect requires "${window.location.hostname}" to be added in Firebase Console → Authentication → Settings → Authorized domains. You can also sign in with Email & Password below.`
        );
      } else if (code && code !== 'auth/no-current-user') {
        setAuthError(error instanceof Error ? error.message : 'Google redirect sign-in failed.');
      }
    });

    const unsubAuth = onAuthStateChanged(auth, (user) => {
      if (unsubProfile) {
        unsubProfile();
        unsubProfile = null;
      }

      setFirebaseUser(user);
      setAuthError(null);

      if (!user) {
        setProfile(null);
        setNeedsProfileSetup(false);
        setLoading(false);
        return;
      }

      const userPath = `users/${user.uid}`;
      const userRef = doc(db, 'users', user.uid);

      unsubProfile = onSnapshot(
        userRef,
        (snap) => {
          if (snap.exists()) {
            setProfile(snap.data() as UserProfile);
            setNeedsProfileSetup(false);
          } else {
            setProfile(null);
            setNeedsProfileSetup(true);
          }
          setLoading(false);
        },
        (error) => {
          // If document does not exist yet or user isn't verified yet, allow onboarding view
          if (error.code === 'permission-denied') {
            setProfile(null);
            setNeedsProfileSetup(true);
            setLoading(false);
            return;
          }
          handleFirestoreError(error, OperationType.GET, userPath);
        }
      );
    });

    return () => {
      unsubAuth();
      if (unsubProfile) unsubProfile();
    };
  }, []);

  const writeInitialProfile = useCallback(
    async (
      user: User,
      params: {
        handle: string;
        displayName: string;
        teamName: string;
        requestOrganizer: boolean;
      }
    ) => {
      const isBootstrap =
        !!BOOTSTRAP_ADMIN_EMAIL &&
        user.email?.toLowerCase() === BOOTSTRAP_ADMIN_EMAIL && user.emailVerified;
      const safeHandle = sanitizeHandle(params.handle);
      const safeDisplay = params.displayName.trim().slice(0, 80) || safeHandle;
      const safeTeam = params.teamName.trim().slice(0, 64);
      const role = isBootstrap ? 'admin' : 'player';
      const requestedRole: RequestedRole =
        !isBootstrap && params.requestOrganizer ? 'organizer' : 'none';

      const userPath = `users/${user.uid}`;
      try {
        await setDoc(doc(db, 'users', user.uid), {
          uid: user.uid,
          handle: safeHandle,
          displayName: safeDisplay,
          teamName: safeTeam,
          role,
          requestedRole,
          status: 'active',
          createdAt: serverTimestamp(),
          updatedAt: serverTimestamp(),
        });
      } catch (error) {
        handleFirestoreError(error, OperationType.CREATE, userPath);
      }

      if (user.email) {
        const privPath = `users/${user.uid}/private/account`;
        try {
          await setDoc(doc(db, 'users', user.uid, 'private', 'account'), {
            uid: user.uid,
            email: user.email.slice(0, 254),
            updatedAt: serverTimestamp(),
          });
        } catch (error) {
          handleFirestoreError(error, OperationType.CREATE, privPath);
        }
      }

      if (isBootstrap) {
        const adminPath = `admins/${user.uid}`;
        try {
          const existingAdmin = await getDoc(doc(db, 'admins', user.uid));
          if (!existingAdmin.exists()) {
            await setDoc(doc(db, 'admins', user.uid), {
              uid: user.uid,
              grantedBy: 'bootstrap',
              createdAt: serverTimestamp(),
            });
          }
        } catch (error) {
          handleFirestoreError(error, OperationType.CREATE, adminPath);
        }
      }
    },
    []
  );

const loginWithGoogle = useCallback(async () => {
  setAuthError(null);

  const isDesktopWebview =
    isTauri() ||
    (typeof window !== 'undefined' &&
      ('__TAURI_INTERNALS__' in window ||
        '__TAURI__' in window ||
        window.location.hostname === 'tauri.localhost' ||
        window.location.protocol === 'tauri:' ||
        navigator.userAgent.includes('Tauri')));

  try {
    if (isDesktopWebview) {
      await signInWithGoogleTauri();
      return;
    }
    await signInWithPopup(auth, googleProvider);
  } catch (error) {
    if (isDesktopWebview) {
      const msg =
        typeof error === 'string'
          ? error
          : error instanceof Error
            ? error.message
            : JSON.stringify(error);
      setAuthError(msg || 'Desktop Google sign-in failed.');
      throw error;
    }

    const code = (error as { code?: string })?.code || '';
    if (
      code === 'auth/popup-blocked' ||
      code === 'auth/operation-not-supported-in-this-environment'
    ) {
      let isInIframe = false;
      try {
        isInIframe = window.self !== window.top;
      } catch {
        isInIframe = true;
      }

      if (isInIframe) {
        setAuthError(
          'Browser blocked Google Sign-In because this app is running inside an embedded preview frame. Click "Open in new tab" on the preview toolbar, or use Email & Password below.'
        );
        throw error;
      }

      try {
        await signInWithRedirect(auth, googleProvider);
        return;
      } catch (redirErr) {
        setAuthError(
          'Popup and redirect were both blocked by browser settings. Allow pop-ups for this site in your address bar, or sign in with Email & Password below.'
        );
        throw redirErr;
      }
    }

    if (code === 'auth/unauthorized-domain') {
      setAuthError(
        `Google Sign-In requires "${window.location.hostname}" in Firebase Console → Authentication → Settings → Authorized domains. Use Email & Password sign-in below for immediate desktop access.`
      );
      throw error;
    }

    const msg = error instanceof Error ? error.message : 'Google sign-in failed.';
    setAuthError(msg);
    throw error;
  }
}, []);

  const loginWithEmail = useCallback(async (email: string, password: string) => {
    setAuthError(null);
    try {
      await signInWithEmailAndPassword(auth, email.trim(), password);
    } catch (error) {
      const code = (error as { code?: string })?.code || '';
      if (code === 'auth/operation-not-allowed') {
        setAuthError(
          'Email/Password authentication is not yet enabled in your Firebase Console (Authentication -> Sign-in method -> Email/Password). Use Google Sign-In for instant access.'
        );
      } else if (code === 'auth/invalid-credential' || code === 'auth/wrong-password') {
        setAuthError('Invalid email or password.');
      } else {
        setAuthError(error instanceof Error ? error.message : 'Sign-in failed.');
      }
      throw error;
    }
  }, []);

  const registerWithEmail = useCallback(
    async (params: {
      email: string;
      password: string;
      handle: string;
      displayName: string;
      teamName: string;
      requestOrganizer: boolean;
    }) => {
      setAuthError(null);
      try {
        const cred = await createUserWithEmailAndPassword(
          auth,
          params.email.trim(),
          params.password
        );
        await updateProfile(cred.user, {
          displayName: params.displayName.trim().slice(0, 80) || params.handle,
        });
        await sendEmailVerification(cred.user);
        // Store pending onboarding details locally until email is verified
        localStorage.setItem(
          `atlas_pending_reg_${cred.user.uid}`,
          JSON.stringify({
            handle: params.handle,
            displayName: params.displayName,
            teamName: params.teamName,
            requestOrganizer: params.requestOrganizer,
          })
        );
        return { verificationSent: true };
      } catch (error) {
        const code = (error as { code?: string })?.code || '';
        if (code === 'auth/operation-not-allowed') {
          setAuthError(
            'Email/Password registration is not enabled in Firebase Console yet. Enable it under Authentication -> Sign-in method -> Email/Password, or register immediately with Google Sign-In.'
          );
        } else if (code === 'auth/email-already-in-use') {
          setAuthError('An account with this email already exists. Switch to Sign In.');
        } else if (code === 'auth/weak-password') {
          setAuthError('Password must be at least 6 characters long.');
        } else {
          setAuthError(error instanceof Error ? error.message : 'Registration failed.');
        }
        throw error;
      }
    },
    []
  );

  const completeProfileSetup = useCallback(
    async (params: {
      handle: string;
      displayName: string;
      teamName: string;
      requestOrganizer: boolean;
    }) => {
      if (!firebaseUser) return;
      await writeInitialProfile(firebaseUser, params);
      localStorage.removeItem(`atlas_pending_reg_${firebaseUser.uid}`);
    },
    [firebaseUser, writeInitialProfile]
  );

  const updateMyProfile = useCallback(
    async (params: {
      handle: string;
      displayName: string;
      teamName: string;
      requestedRole: RequestedRole;
    }) => {
      if (!firebaseUser || !profile) return;
      const userPath = `users/${firebaseUser.uid}`;
      try {
        await updateDoc(doc(db, 'users', firebaseUser.uid), {
          handle: sanitizeHandle(params.handle),
          displayName: params.displayName.trim().slice(0, 80) || profile.displayName,
          teamName: params.teamName.trim().slice(0, 64),
          requestedRole: params.requestedRole,
          updatedAt: serverTimestamp(),
        });
      } catch (error) {
        handleFirestoreError(error, OperationType.UPDATE, userPath);
      }
    },
    [firebaseUser, profile]
  );

  const resendVerification = useCallback(async () => {
    if (!auth.currentUser) return;
    await sendEmailVerification(auth.currentUser);
  }, []);

  const refreshUser = useCallback(async () => {
    if (!auth.currentUser) return;
    await auth.currentUser.reload();
    setFirebaseUser(auth.currentUser);
  }, []);

  const logout = useCallback(async () => {
    await signOut(auth);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        firebaseUser,
        profile,
        loading,
        needsProfileSetup,
        authError,
        clearAuthError,
        loginWithGoogle,
        loginWithEmail,
        registerWithEmail,
        completeProfileSetup,
        updateMyProfile,
        logout,
        resendVerification,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
