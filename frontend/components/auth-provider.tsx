"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import * as authApi from "@/lib/api/auth";
import type { User } from "@/lib/api/auth";
import { clearDraft } from "@/lib/draft";
import {
  clearSession,
  initSessionSync,
  refreshAccessToken,
  setAccessToken,
  subscribe,
} from "@/lib/auth/session";

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  /** True after the user chose to sign out or deleted the account (so gates go home, not to /login). */
  signedOutOnPurpose: boolean;
  login: (input: { email: string; password: string }) => Promise<void>;
  signup: (input: { email: string; password: string; name: string }) => Promise<void>;
  logout: () => Promise<void>;
  /** Re-read `/auth/me` (e.g. after verifying email). Silent on failure. */
  refreshUser: () => Promise<void>;
  /** Replace the cached user (after a profile edit or an optimistic rollback). */
  applyUser: (user: User) => void;
  /** End the local session without calling the API (the account no longer exists). */
  discardSession: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// One bootstrap per page load, shared by React Strict Mode's double effect (G-22).
let bootstrapPromise: Promise<User | null> | null = null;

async function bootstrap(): Promise<User | null> {
  const token = await refreshAccessToken();
  if (!token) return null;
  return authApi.fetchMe();
}

/** Test helper: allow a fresh bootstrap. */
export function __resetBootstrapForTests(): void {
  bootstrapPromise = null;
}

/** Holds the in-memory session state; bootstraps via `/auth/refresh` on mount (plan §5.3). */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [signedOutOnPurpose, setSignedOutOnPurpose] = useState(false);

  const endSession = useCallback(() => {
    setUser(null);
    setStatus("unauthenticated");
    // The draft is kept on an expired session (restored only for the same user, `lib/draft.ts`);
    // a deliberate sign-out clears it below.
    queryClient.clear(); // R16: no cached data survives sign-out.
  }, [queryClient]);

  useEffect(() => {
    let active = true;
    initSessionSync();
    bootstrapPromise ??= bootstrap();
    bootstrapPromise
      .then((me) => {
        if (!active) return;
        setUser(me);
        setStatus(me ? "authenticated" : "unauthenticated");
      })
      .catch(() => {
        // API unreachable at startup: show the signed-out UI rather than a stuck skeleton.
        if (active) setStatus("unauthenticated");
      });
    const unsubscribe = subscribe((event) => {
      if (event === "cleared") endSession();
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [endSession]);

  const establish = useCallback(async (token: string) => {
    setAccessToken(token);
    setSignedOutOnPurpose(false);
    setUser(await authApi.fetchMe());
    setStatus("authenticated");
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      setUser(await authApi.fetchMe());
    } catch {
      // Keep the current view; a 401 already ended the session via the HTTP client.
    }
  }, []);

  // R11: pick up an email verified in another tab/browser when the user returns.
  const needsVerification = status === "authenticated" && user !== null && !user.email_verified_at;
  useEffect(() => {
    if (!needsVerification) return;
    const onFocus = () => void refreshUser();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [needsVerification, refreshUser]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      signedOutOnPurpose,
      login: async (input) => establish(await authApi.login(input)),
      signup: async (input) => establish(await authApi.signup(input)),
      logout: async () => {
        try {
          await authApi.logout();
        } catch {
          // Offline logout still clears local state; the cookie expires on its own.
        }
        setSignedOutOnPurpose(true);
        clearDraft();
        clearSession();
        endSession();
      },
      refreshUser,
      applyUser: setUser,
      discardSession: () => {
        setSignedOutOnPurpose(true);
        clearDraft();
        clearSession();
        endSession();
      },
    }),
    [status, user, signedOutOnPurpose, establish, endSession, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
