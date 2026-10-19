"use client";

/**
 * Fixes in flight, kept in memory per part (like the check store), so the dialog
 * can close and the page can change while a repair or a new Design Studio revision
 * runs, and the result is still there to compare. Nothing here is saved: a repaired
 * copy is kept only when the user saves it, which checks it like an upload.
 */
import * as React from "react";
import { createDesignRevision, getDesign, type Design, type DesignPlan } from "@/lib/designs-api";
import { importDesignStep } from "@/lib/verify/design-import";
import { runRepair, type RepairOutcome } from "../part/repair";
import { startCheck } from "../part/store";
import type { ServerFix, StudioOrigin, StudioParam } from "./capabilities";
import { applyServerFix, type ServerFixOutcome } from "./server";

export type RepairRun = { kind: "repair"; problem: string; startedAt: number; sourceName: string } & ({ s: "running" } | RepairOutcome);

export interface StudioRun {
  kind: "studio";
  problem: string;
  startedAt: number;
  designId: string;
  designName: string;
  from: { revision: number; plan: DesignPlan; volumeCm3: number | null };
  /** The first change (the problem that was asked about). */
  param: StudioParam;
  value: number;
  /** Every parameter this revision changes, the asked one first. */
  changes: { problem: string; param: StudioParam; value: number }[];
  /** generating → checking → done; or failed with the reason. */
  s: "generating" | "checking" | "done" | "failed";
  revision: number | null;
  volumeCm3: number | null;
  sessionId: number | null;
  error: string | null;
}

/** A fix the server makes on a copy of the kept CAD (POST /parts/{hash}/fixes/{id}). */
export type ServerRun = { kind: "server"; problem: string; startedAt: number; fix: ServerFix; value: number | null } & ({ s: "running" } | ServerFixOutcome);

export type FixRun = RepairRun | StudioRun | ServerRun;

const runs = new Map<string, FixRun>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version += 1;
  for (const l of listeners) l();
}

function put(key: string, run: FixRun) {
  runs.set(key, run);
  emit();
}

function patch(key: string, p: Partial<StudioRun>) {
  const r = runs.get(key);
  if (!r || r.kind !== "studio") return;
  runs.set(key, { ...r, ...p });
  emit();
}

export function useFixRun(key: string | null): FixRun | null {
  return React.useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => (key ? runs.get(key) ?? null : null),
    () => null,
  );
}

export function useRunsVersion(): number {
  return React.useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => version,
    () => 0,
  );
}

/** Forget a run (discard the repaired copy, or leave the comparison). */
export function clearRun(key: string) {
  const r = runs.get(key);
  if (r?.kind === "repair" && r.s === "fixed") URL.revokeObjectURL(r.url);
  runs.delete(key);
  emit();
}

/** Repair a copy of the file (POST /validate/repair). */
export function startRepair(key: string, problem: string, file: File) {
  const prev = runs.get(key);
  if (prev?.kind === "repair" && prev.s === "fixed") URL.revokeObjectURL(prev.url);
  const startedAt = Date.now();
  put(key, { kind: "repair", problem, startedAt, sourceName: file.name, s: "running" });
  void runRepair(file).then((out) => {
    const cur = runs.get(key);
    // Discarded, or a newer repair started meanwhile: drop this answer.
    if (!cur || cur.kind !== "repair" || cur.startedAt !== startedAt) {
      if (out.s === "fixed") URL.revokeObjectURL(out.url);
      return;
    }
    put(key, { kind: "repair", problem, startedAt, sourceName: file.name, ...out } as RepairRun);
  });
}

/** Make the server's fix on a copy of this part's kept source; it re-checks and prices both in the same request. */
export function startServerFix(key: string, problem: string, fix: ServerFix, value: number | null, opts: { qty?: number[]; materialClass?: string | null }) {
  if (!fix.fix) return;
  const startedAt = Date.now();
  put(key, { kind: "server", problem, startedAt, fix, value, s: "running" });
  void applyServerFix(key, fix.fix, { value, qty: opts.qty, materialClass: opts.materialClass }).then((out) => {
    const cur = runs.get(key);
    if (!cur || cur.kind !== "server" || cur.startedAt !== startedAt) return;
    put(key, { kind: "server", problem, startedAt, fix, value, ...out } as ServerRun);
  });
}

async function waitForRevision(designId: string, n: number): Promise<Design> {
  const t0 = Date.now();
  for (;;) {
    const d = await getDesign(designId);
    if (d.current_revision >= n && d.revision && d.revision.number === n) {
      if (d.revision.status === "ready") return d;
      if (d.revision.status === "failed") throw new Error(d.revision.error?.message ?? `Revision ${n} wasn’t generated.`);
    }
    if (Date.now() - t0 > 5 * 60_000) throw new Error(`Revision ${n} is still generating. It will appear in Design Studio when it’s done.`);
    await new Promise((r) => setTimeout(r, 1500));
  }
}

/** Generate the next revision with one parameter changed, then check it like an upload. */
export function startStudioRevision(key: string, origin: StudioOrigin, changes: { problem: string; param: StudioParam; value: number }[], materialClass: string) {
  const { problem, param, value } = changes[0];
  const plan = { ...origin.plan } as Record<string, unknown>;
  for (const c of changes) plan[c.param.key] = c.value;
  put(key, {
    kind: "studio",
    problem,
    startedAt: Date.now(),
    designId: origin.designId,
    designName: origin.designName,
    from: { revision: origin.revision, plan: origin.plan, volumeCm3: origin.volumeCm3 },
    param,
    value,
    changes,
    s: "generating",
    revision: null,
    volumeCm3: null,
    sessionId: null,
    error: null,
  });
  void (async () => {
    try {
      const note = `${changes.map((c) => `${c.param.label} ${c.param.value}${c.param.unit === "°" ? "°" : " mm"} → ${c.value}${c.param.unit === "°" ? "°" : " mm"}`).join(", ")}, from the check on revision ${origin.revision}`;
      const created = await createDesignRevision(origin.designId, { plan: plan as unknown as DesignPlan, design_note: note });
      const n = created.current_revision;
      patch(key, { revision: n });
      const ready = await waitForRevision(origin.designId, n);
      const file = await importDesignStep(origin.designId, fetch, n);
      const sessionId = startCheck(file, { materialClass });
      patch(key, { s: "checking", sessionId, volumeCm3: ready.revision?.geometry?.volume_cm3 ?? null });
    } catch (e) {
      patch(key, { s: "failed", error: e instanceof Error ? e.message : "The new revision wasn’t made." });
    }
  })();
}

export function markStudioDone(key: string) {
  patch(key, { s: "done" });
}
