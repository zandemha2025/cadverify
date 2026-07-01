"use client";

import * as React from "react";

/**
 * Client auth context. The authoritative session is server-side (the (app)
 * layout calls `verifySession()` and passes the resolved user down here); this
 * provider just exposes that identity to client components (account menu) and a
 * `signOut()` that clears the first-party cookie via the logout route. There is
 * NO localStorage/API-key state anymore — the platform is session-gated.
 */
export type SessionUser = {
  id: number;
  email: string;
  role: string;
  auth_provider: string;
};

interface AuthState {
  user: SessionUser | null;
  signOut: () => Promise<void>;
}

const AuthContext = React.createContext<AuthState>({
  user: null,
  signOut: async () => {},
});

export function AuthProvider({
  user,
  children,
}: {
  user: SessionUser | null;
  children: React.ReactNode;
}) {
  const signOut = React.useCallback(async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      // Hard navigation so the server re-evaluates the (cleared) session.
      window.location.href = "/login";
    }
  }, []);

  const value = React.useMemo<AuthState>(
    () => ({ user, signOut }),
    [user, signOut]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return React.useContext(AuthContext);
}
