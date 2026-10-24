"use client";

/**
 * The first run's client state, in memory and in this browser only:
 *
 * - which files were held on this device through sign-in (so the first check
 *   says "Held from sign-up"), by name, size and modified time, because the
 *   check store copies the File;
 * - the re-check after "Make it about your shop": the part, the answer it was
 *   re-checked from ("before"), and the check that is running ("now");
 * - the tips and shop card, remembered per person in localStorage (a private
 *   window simply shows them again; nothing depends on it).
 */
import * as React from "react";
import type { CostReport } from "@/lib/api";
import { parseTips, tipsKey, type TipsState } from "./first-run";

/* ── held from sign-up ─────────────────────────────────────────────────── */

const held = new Set<string>();

function sig(f: File): string {
  return `${f.name}\u0000${f.size}\u0000${f.lastModified}`;
}

export function markHeld(file: File): void {
  held.add(sig(file));
}

export function isHeld(file: File | null | undefined): boolean {
  return !!file && held.has(sig(file));
}

/* ── the re-check on your machines ─────────────────────────────────────── */

export interface Recheck {
  key: string;
  /** the answer before your machines: the first check's report */
  before: CostReport;
  /** the check session that re-checks it (null until it starts) */
  sessionId: number | null;
  /** names of the machines it re-checks against */
  machines: string[];
  startedAt: number;
  /** closed by the person (Done, another lens); the part page reads normally again */
  closed: boolean;
}

let recheck: Recheck | null = null;
const listeners = new Set<() => void>();
let shopOpenFor: string | null = null;

function emit() {
  for (const l of listeners) l();
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function startRecheck(r: Omit<Recheck, "closed" | "startedAt">): void {
  recheck = { ...r, startedAt: Date.now(), closed: false };
  emit();
}

export function attachSession(key: string, sessionId: number): void {
  if (recheck?.key !== key) return;
  recheck = { ...recheck, sessionId };
  emit();
}

export function closeRecheck(): void {
  if (!recheck) return;
  recheck = { ...recheck, closed: true };
  emit();
}

export function useRecheck(key: string | null): Recheck | null {
  return React.useSyncExternalStore(
    subscribe,
    () => (key && recheck?.key === key && !recheck.closed ? recheck : null),
    () => null,
  );
}

/** "Make it about your shop" opened over a part (from the shop card, Home or a link). */
export function openShopSheet(key: string): void {
  shopOpenFor = key;
  emit();
}

export function closeShopSheet(): void {
  shopOpenFor = null;
  emit();
}

export function useShopSheet(key: string | null): boolean {
  return React.useSyncExternalStore(subscribe, () => !!key && shopOpenFor === key, () => false);
}

/* ── tips, remembered per person ───────────────────────────────────────── */

export function readTips(userId: number | string | null | undefined): TipsState | null {
  if (userId == null) return null;
  try {
    return parseTips(window.localStorage.getItem(tipsKey(userId)));
  } catch {
    return parseTips(null);
  }
}

export function writeTips(userId: number | string | null | undefined, s: TipsState): void {
  if (userId == null) return;
  try {
    window.localStorage.setItem(tipsKey(userId), JSON.stringify(s));
  } catch {
    /* storage off: the tips still close for this visit */
  }
}

/* ── Home's first-run sheet, dismissed per person ──────────────────────── */

export function setupDismissKey(userId: number | string): string {
  return `scalecad_firstrun_home_v1:${userId}`;
}

export function readSetupDismissed(userId: number | string | null | undefined): boolean {
  if (userId == null) return false;
  try {
    return window.localStorage.getItem(setupDismissKey(userId)) === "1";
  } catch {
    return false;
  }
}

export function writeSetupDismissed(userId: number | string, v: boolean): void {
  try {
    if (v) window.localStorage.setItem(setupDismissKey(userId), "1");
    else window.localStorage.removeItem(setupDismissKey(userId));
  } catch {
    /* storage off: Home goes back to the usual view for this visit */
  }
}
