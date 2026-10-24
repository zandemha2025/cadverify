"use client";

import { createContext, useContext } from "react";

/** Optimistic signed-in hint for public pages: true when a session cookie is
 * present. The app's own gate still validates the session server-side, so a
 * stale cookie only changes which button the visitor sees. */
const SignedInContext = createContext(false);

export function SignedInProvider({ signedIn, children }: { signedIn: boolean; children: React.ReactNode }) {
  return <SignedInContext.Provider value={signedIn}>{children}</SignedInContext.Provider>;
}

export function useSignedIn(): boolean {
  return useContext(SignedInContext);
}
