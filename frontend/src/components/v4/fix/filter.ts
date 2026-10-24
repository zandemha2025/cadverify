"use client";

/**
 * "Show problems for": one process, or all of them, remembered per part in this
 * browser (a convenience only; the part and its problems don't change). Shared by
 * the problem list (K4) and the problem view (K1) so stepping through problems
 * stays on the process you chose.
 */
import * as React from "react";

const KEY = "v4.problems.for";
const listeners = new Set<() => void>();
let mem: Record<string, string> | null = null;

function read(): Record<string, string> {
  if (mem) return mem;
  try {
    const v = JSON.parse(window.localStorage.getItem(KEY) ?? "{}");
    mem = v && typeof v === "object" ? (v as Record<string, string>) : {};
  } catch {
    mem = {};
  }
  return mem;
}

function write(next: Record<string, string>) {
  mem = next;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage blocked: remembered until the page reloads */
  }
  for (const l of listeners) l();
}

/** The process this part's problems are shown for (null: all), and a setter. */
export function useProblemFilter(partKey: string | null, processes: string[]): [string | null, (code: string | null) => void] {
  const stored = React.useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => (partKey ? read()[partKey] ?? null : null),
    () => null,
  );
  const value = stored && processes.includes(stored) ? stored : null;
  const set = React.useCallback(
    (code: string | null) => {
      if (!partKey) return;
      const next = { ...read() };
      if (code) next[partKey] = code;
      else delete next[partKey];
      write(next);
    },
    [partKey],
  );
  return [value, set];
}
