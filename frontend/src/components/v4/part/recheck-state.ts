"use client";

/**
 * The kept-file re-check running for a part, readable anywhere on its page (buyer-04, me-14).
 * The page's toast sat far from "Re-verify with saved specs" and a buyer saw nothing happen
 * for a minute; the button now says it is re-checking, and for how long, where it was pressed.
 */
import * as React from "react";

export interface StoredRecheckState {
  key: string;
  startedAt: number;
  /** On ScaleCAD's worker: the web request ran out of time, or the file is large. */
  worker: boolean;
}

let state: StoredRecheckState | null = null;
const subs = new Set<() => void>();

export function setStoredRecheck(next: StoredRecheckState | null): void {
  state = next;
  for (const fn of subs) fn();
}

function subscribe(fn: () => void): () => void {
  subs.add(fn);
  return () => subs.delete(fn);
}

/** The re-check running for this part, with the seconds it has run (ticking), else null. */
export function useStoredRecheck(key: string | null | undefined): (StoredRecheckState & { seconds: number }) | null {
  const s = React.useSyncExternalStore(subscribe, () => (state && state.key === key ? state : null), () => null);
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (!s) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [s]);
  return s ? { ...s, seconds: Math.max(0, Math.round((now - s.startedAt) / 1000)) } : null;
}

/** "Re-checking… 0:35" for the button that started it. */
export function recheckingLabel(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `Re-checking… ${m}:${String(s).padStart(2, "0")}`;
}
