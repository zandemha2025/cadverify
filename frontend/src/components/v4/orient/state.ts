"use client";

/**
 * Orientation mode on one part page, kept in memory like the check store so the
 * stage (the 3D view) and the sheet read the same thing: whether it's open, the
 * orientation the part is turned to, what the 3D view colours, and a re-check
 * in flight or done (with the answer from before it, to compare). Nothing here
 * is saved: the re-check itself is a check of the same file, saved as usual.
 */
import * as React from "react";
import type { CostReport, ValidationResult } from "@/lib/api";
import type { ViewerOrient } from "../part/viewer";
import { IDENTITY, downTo, type Mat, type Shade } from "./orient";

export interface OrientRecheck {
  startedAt: number;
  /** The answer shown before the re-check, and its orientation. */
  before: { validation: ValidationResult | null; cost: CostReport | null; rotation: Mat };
  /** The orientation asked for. */
  rotation: Mat;
}

export interface OrientState {
  key: string;
  /** The orientation the part is turned to on screen (file → placed). */
  target: Mat;
  /** The face picked in the 3D view, in the file's coordinates (laid down when picked). */
  picked: number[] | null;
  shade: (Shade & { color: string }) | null;
  recheck: OrientRecheck | null;
  /** In a comparison, which side the 3D view shows. */
  showing: "now" | "before";
}

let state: OrientState | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

export function useOrient(key: string | null): OrientState | null {
  return React.useSyncExternalStore(subscribe, () => (key && state?.key === key ? state : null), () => null);
}

export function getOrient(): OrientState | null {
  return state;
}

export function openOrient(key: string, from: Mat) {
  state = { key, target: [...from], picked: null, shade: null, recheck: null, showing: "now" };
  emit();
}

export function closeOrient() {
  if (!state) return;
  state = null;
  emit();
}

export function patchOrient(p: Partial<OrientState>) {
  if (!state) return;
  state = { ...state, ...p };
  emit();
}

/** A face clicked in the 3D view: lay the part on it. */
export function pickFace(normal: [number, number, number]) {
  if (!state || state.recheck) return;
  const r = downTo(normal);
  if (!r) return;
  state = { ...state, target: r, picked: normal };
  emit();
}

/** What the 3D view of this part shows while orientation mode is open (null: the file's own view). */
export function useOrientView(key: string | null): { orient: ViewerOrient | null; onFacePick?: (normal: [number, number, number]) => void } {
  const s = useOrient(key);
  return React.useMemo(() => {
    if (!s) return { orient: null };
    const rotation = s.recheck && s.showing === "before" ? s.recheck.before.rotation : s.target;
    return { orient: { rotation: rotation ?? IDENTITY, shade: s.shade }, onFacePick: s.recheck ? undefined : pickFace };
  }, [s]);
}
