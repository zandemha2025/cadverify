"use client";

/**
 * The live check: one module-level store that runs the real check
 * (`runVerification`) for a file and keeps the result in memory, so the check
 * page can hand over to the part page mid-run and the part page can show the
 * result without fetching it back. It also keeps a copy of the preview mesh in
 * this browser (mesh-cache) so the part reopens in 3D later.
 */
import * as React from "react";
import type { ValidationResult } from "@/lib/api";
import { isSupportedCad, unsupportedCadGuidance } from "@/lib/cad-file";
import { clientStlIntegrityError } from "@/lib/stl-validation";
import { isPhoneVerificationMessage, isQuotaErrorMessage } from "@/lib/api-recovery";
import { analysisFailureCopy } from "@/lib/verify/failure-copy";
import { computeMeshHash } from "@/lib/verify/part-context";
import { fetchPreviewMesh } from "@/lib/verify/preview-mesh";
import { isAssemblyCandidate } from "@/lib/verify/assembly";
import { closedBodies, isMultiBody } from "@/lib/verify/bodies";
import type { AssemblyAnalysis, AssemblyModel } from "@/lib/verify/assembly";
import { retryVerificationCost, runVerification, type VerifyResult } from "@/lib/verify/run";
import { resolvedAnnualVolume } from "@/lib/verify/program-rollup";
import { putCachedMesh } from "./mesh-cache";
import { fetchAssemblyAnalysisV4, probeAssemblyV4 } from "./api";
import { markWorkSeen, registerWork } from "../work/work-bar";
import { R } from "../routes";

export type Failure =
  | { kind: "quota"; message: string }
  | { kind: "phone"; message: string }
  | { kind: "interrupted"; message: string }
  | { kind: "unreadable"; title: string; detail: string; problem: "open" | "unreadable" | "unsupported" | "geometry" | "refused"; retry: boolean };

export interface PreviewState {
  status: "loading" | "ready" | "failed";
  url: string | null;
  faceHash: string | null;
  faceSpace: "analysis" | "preview";
  error: string | null;
}

export interface AssemblyState {
  model: AssemblyModel;
  glbUrl: string | null;
  gate: "pilot" | null;
  glbError: string | null;
  analysis: AssemblyAnalysis | null;
  analyzing: boolean;
  analysisGate: "pilot" | null;
  analysisError: string | null;
}

export interface CheckSession {
  id: number;
  file: File;
  sample: boolean;
  /** The material to price in: the answer to "What will it be made of?", else plastic. */
  materialClass: string;
  /** The material the latest price request was sent with (null before pricing starts). */
  pricedWith: string | null;
  /** Started without a material (a new upload, not the sample or a re-check): the progress panel asks for one (N1). */
  askMaterial: boolean;
  /** The orientation this check turns the part to ("rotation:…"); null for the file's own. */
  orientation: string | null;
  /** An order quantity priced exactly (carried from the cost breakdown's Check another part); null for the standard ladder. */
  quantity: number | null;
  key: string | null;
  startedAt: number;
  validatedAt: number | null;
  finishedAt: number | null;
  status: "running" | "done" | "failed" | "stopped" | "assembly";
  validation: ValidationResult | null;
  result: VerifyResult | null;
  failure: Failure | null;
  costRetrying: boolean;
  preview: PreviewState;
  assembly: AssemblyState | null;
  /** Whether the progress panel is showing; it survives the hand-over to the part page. */
  panel: boolean;
  /** Its result has been on screen (the part page or the check page), so the work bar lets it go. */
  opened?: boolean;
}

/**
 * A file of several bodies the part page reads body by body: closed bodies (even
 * when, as one mesh, they share edges and so aren't one closed solid), or a
 * STEP/IGES file, whose product tree holds each part as a closed solid of its own.
 */
export function readsAsBodies(v: ValidationResult | null | undefined, fileName: string): boolean {
  const pt = v?.part_type;
  if (!isMultiBody(pt)) return false;
  return closedBodies(pt) || /\.(step|stp|iges|igs)$/i.test(fileName);
}

let nextId = 1;
const sessions = new Map<number, CheckSession>();
const byKey = new Map<string, number>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version += 1;
  for (const l of listeners) l();
}

function patch(id: number, p: Partial<CheckSession> | ((s: CheckSession) => Partial<CheckSession>)) {
  const s = sessions.get(id);
  if (!s) return;
  const next = { ...s, ...(typeof p === "function" ? p(s) : p) };
  sessions.set(id, next);
  if (next.key) byKey.set(next.key, id);
  if (next.status !== s.status || next.key !== s.key || !!next.validation !== !!s.validation) syncWork(next);
  emit();
}

/* ── the work bar: a check you leave stays one click away ──────────────── */

const workKey = (id: number) => `check:${id}`;

/**
 * The work bar's item for a check (work/work-bar.tsx), from start until its result
 * has been on screen. It links to the part once the check page has handed over to
 * it (a closed solid), else to the check page, which resumes the newest check.
 */
function syncWork(s: CheckSession) {
  if (s.opened && s.status !== "running") return markWorkSeen(workKey(s.id));
  const name = s.sample ? "the sample bracket" : s.file.name;
  const handed = !!s.key && (s.validation?.geometry.is_watertight === true || readsAsBodies(s.validation, s.file.name));
  const href = handed ? R.part(s.key!) : R.check;
  const item = s.status === "running"
    ? { label: `Checking ${name}`, detail: s.validation ? "Measured · pricing" : "Measuring", state: "running" as const }
    : s.status === "done" || s.status === "assembly"
      ? { label: `Checked ${name}`, detail: "Ready", state: "done" as const }
      : s.status === "stopped"
        ? { label: `${name}: not a closed solid`, detail: "Nothing priced · repair it or upload a fixed file", state: "stopped" as const }
        : { label: `${name}: not checked`, detail: s.failure && "title" in s.failure ? s.failure.title : "The check didn’t finish", state: "stopped" as const };
  registerWork({ key: workKey(s.id), href, persist: false, progress: null, ...item });
}

/** The check's result is on screen: the work bar lets a finished one go. */
export function markCheckOpened(id: number) {
  const s = sessions.get(id);
  if (!s || s.opened || s.status === "running") return;
  sessions.set(id, { ...s, opened: true });
  markWorkSeen(workKey(id));
  emit();
}

/** The newest check still running, or finished and not yet opened: what the check page resumes. */
export function resumableSession(): number | null {
  let best: CheckSession | null = null;
  for (const s of sessions.values()) if ((s.status === "running" || !s.opened) && (!best || s.startedAt > best.startedAt)) best = s;
  return best?.id ?? null;
}

export function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function getSession(id: number | null): CheckSession | null {
  return id == null ? null : sessions.get(id) ?? null;
}

export function sessionForKey(key: string | null): CheckSession | null {
  if (!key) return null;
  const id = byKey.get(key);
  return id == null ? null : sessions.get(id) ?? null;
}

export function useSession(id: number | null): CheckSession | null {
  return React.useSyncExternalStore(subscribe, () => getSession(id), () => null);
}

export function useSessionForKey(key: string | null): CheckSession | null {
  return React.useSyncExternalStore(subscribe, () => sessionForKey(key), () => null);
}

export function useStoreVersion(): number {
  return React.useSyncExternalStore(subscribe, () => version, () => 0);
}

function classify(message: string | null): Failure {
  const m = message ?? "";
  if (isPhoneVerificationMessage(m)) return { kind: "phone", message: m };
  if (isQuotaErrorMessage(m)) return { kind: "quota", message: m };
  const copy = analysisFailureCopy(m);
  if (copy.kind === "quota" || copy.kind === "quota-window") return { kind: "quota", message: m };
  if (copy.kind === "capacity" || copy.kind === "unknown") return { kind: "interrupted", message: m || copy.explanation };
  return { kind: "unreadable", title: copy.title.replace(/\.$/, ""), detail: copy.action, problem: copy.kind === "geometry" ? "geometry" : copy.kind === "unsupported" ? "unsupported" : "unreadable", retry: false };
}

async function loadPreview(id: number) {
  const s = sessions.get(id);
  if (!s) return;
  patch(id, { preview: { status: "loading", url: null, faceHash: null, faceSpace: "preview", error: null } });
  try {
    const pm = await fetchPreviewMesh(s.file, { forAnalysis: true, units: "mm" });
    if (!pm) throw new Error("The 3D preview couldn't be built from this file.");
    patch(id, { preview: { status: "ready", url: pm.url, faceHash: pm.faceHash, faceSpace: pm.faceSpace, error: null } });
    const key = sessions.get(id)?.key ?? (await computeMeshHash(s.file).catch(() => null));
    if (key) {
      const blob = await fetch(pm.url).then((r) => r.blob()).catch(() => null);
      if (blob) void putCachedMesh({ hash: key, blob, faceHash: pm.faceHash, faceSpace: pm.faceSpace, filename: s.file.name, savedAt: Date.now() });
    }
  } catch (e) {
    patch(id, { preview: { status: "failed", url: null, faceHash: null, faceSpace: "preview", error: e instanceof Error ? e.message : "No 3D preview" } });
  }
}

async function runAssembly(id: number) {
  const s = sessions.get(id);
  if (!s?.assembly) return;
  patch(id, (x) => ({ assembly: x.assembly && { ...x.assembly, analyzing: true, analysisError: null } }));
  const out = await fetchAssemblyAnalysisV4(s.file);
  patch(id, (x) => ({ assembly: x.assembly && { ...x.assembly, analyzing: false, analysis: out.analysis, analysisGate: out.gate, analysisError: out.error } }));
}

export function setPanel(id: number, open: boolean) {
  patch(id, { panel: open });
}

/** The same file and the same check id, so asking again doesn't use another check. */
export function retryPreview(id: number) {
  void loadPreview(id);
}

export function retryAssemblyAnalysis(id: number) {
  void runAssembly(id);
}

async function run(id: number) {
  const s0 = sessions.get(id);
  if (!s0) return;
  const file = s0.file;
  if (!isSupportedCad(file.name)) {
    const g = unsupportedCadGuidance(file.name);
    patch(id, { status: "failed", finishedAt: Date.now(), failure: { kind: "unreadable", title: g.title, detail: g.action, problem: "unsupported", retry: false } });
    return;
  }
  if (file.name.toLowerCase().endsWith(".stl")) {
    const bad = await clientStlIntegrityError(file);
    if (bad) {
      patch(id, { status: "failed", finishedAt: Date.now(), failure: { kind: "unreadable", title: "We couldn’t read this STL", detail: "The file ended before its declared triangle data was complete. Re-export the part as a clean STL and upload that.", problem: "unreadable", retry: false } });
      return;
    }
  }
  const key = await computeMeshHash(file).catch(() => null);
  patch(id, { key });

  if (isAssemblyCandidate(file.name)) {
    const probe = await probeAssemblyV4(file);
    // The assembly reader only takes solids. A file it can't read as solids (an open
    // shell, surfaces) still goes through the single-part check, which measures it
    // and says exactly what's wrong instead of refusing it unread.
    const readable = probe.kind === "refused" && probe.status != null && [400, 415, 422].includes(probe.status);
    if (probe.kind === "refused" && !readable) {
      const failure = classify(probe.detail);
      patch(id, {
        status: "failed",
        finishedAt: Date.now(),
        failure: failure.kind === "unreadable" || failure.kind === "interrupted" ? { kind: "unreadable", title: probe.title, detail: probe.detail, problem: "refused", retry: probe.retry } : failure,
      });
      return;
    }
    if (probe.kind === "assembly") {
      patch(id, {
        status: "assembly",
        finishedAt: Date.now(),
        assembly: { model: probe.model, glbUrl: probe.glbUrl, gate: probe.gate, glbError: probe.glbError, analysis: null, analyzing: false, analysisGate: null, analysisError: null },
      });
      if (!probe.gate) void runAssembly(id);
      else patch(id, (x) => ({ assembly: x.assembly && { ...x.assembly, analysisGate: "pilot" } }));
      return;
    }
  }

  void loadPreview(id);
  let result: VerifyResult;
  try {
    result = await runVerification(
      { file, materialClass: s0.materialClass, orientation: s0.orientation, quantity: s0.quantity },
      {
        onValidation: ({ validation }) => {
          if (validation) patch(id, { validation, validatedAt: Date.now() });
        },
        materialClass: () => {
          const m = sessions.get(id)?.materialClass ?? s0.materialClass;
          patch(id, { pricedWith: m });
          return m;
        },
      },
    );
  } catch (e) {
    const message = e instanceof Error ? e.message : "The check didn’t finish.";
    const v = sessions.get(id)?.validation ?? null;
    patch(id, v ? { status: "done", finishedAt: Date.now() } : { status: "failed", finishedAt: Date.now(), failure: classify(message) });
    window.dispatchEvent(new Event("proofshape:usage-changed"));
    return;
  }
  window.dispatchEvent(new Event("proofshape:usage-changed"));
  if (!result.validation) {
    patch(id, { result, status: "failed", finishedAt: Date.now(), failure: classify(result.validationError) });
    return;
  }
  // Several bodies are checked body by body, not stopped as an open shell.
  const open = !readsAsBodies(result.validation, file.name) && (!result.validation.geometry.is_watertight || !!result.costGeometryInvalid);
  patch(id, { result, validation: result.validation, key: result.meshHash ?? key, status: open ? "stopped" : "done", finishedAt: Date.now() });
  // The material changed while the first price ran: price again in it.
  const s1 = sessions.get(id);
  if (!open && s1 && s1.pricedWith != null && s1.materialClass !== s1.pricedWith) void retryPrices(id);
}

/** Start the real check for a file. Returns the session id the pages subscribe to. */
export function startCheck(file: File, opts: { sample?: boolean; materialClass?: string; orientation?: string | null; quantity?: number | null } = {}): number {
  // A deliberate check gets its own allowance id; every request of it shares this File.
  const f = new File([file], file.name, { type: file.type, lastModified: file.lastModified });
  const id = nextId++;
  sessions.set(id, {
    id,
    file: f,
    sample: !!opts.sample,
    materialClass: opts.materialClass ?? "polymer",
    pricedWith: null,
    askMaterial: !opts.sample && opts.materialClass == null,
    orientation: opts.orientation ?? null,
    quantity: opts.quantity ?? null,
    key: null,
    startedAt: Date.now(),
    validatedAt: null,
    finishedAt: null,
    status: "running",
    validation: null,
    result: null,
    failure: null,
    costRetrying: false,
    preview: { status: "loading", url: null, faceHash: null, faceSpace: "preview", error: null },
    assembly: null,
    panel: true,
  });
  syncWork(sessions.get(id)!);
  emit();
  void run(id);
  return id;
}

/** Retry only the prices; methods, findings and machine fit stay as they are. */
export async function retryPrices(id: number) {
  const s = sessions.get(id);
  if (!s?.result?.validation || s.costRetrying) return;
  const materialClass = s.materialClass;
  patch(id, { costRetrying: true, pricedWith: materialClass });
  try {
    const retried = await retryVerificationCost({ file: s.file, materialClass, orientation: s.orientation, quantity: s.quantity }, s.result.machines, resolvedAnnualVolume(s.result.partContext));
    patch(id, (x) => ({ costRetrying: false, result: x.result ? { ...x.result, ...retried } : x.result }));
  } catch (e) {
    patch(id, (x) => ({ costRetrying: false, result: x.result ? { ...x.result, costError: e instanceof Error ? e.message : "Prices didn’t finish." } : x.result }));
  } finally {
    window.dispatchEvent(new Event("proofshape:usage-changed"));
  }
  // Picked another material while this price ran: price in that one too.
  const after = sessions.get(id);
  if (after && after.materialClass !== materialClass) void retryPrices(id);
}

/**
 * The answer to "What will it be made of?" (N1), asked while the geometry check
 * runs, or changed later. Before pricing starts it is the material the first
 * price uses; once a price exists it re-prices in the new material. Same file
 * and check id: no extra check, and the server reuses the geometry it already
 * analysed, so a re-price takes well under a second instead of a full check.
 */
export function setCheckMaterial(id: number, materialClass: string) {
  const s = sessions.get(id);
  if (!s || s.materialClass === materialClass) return;
  patch(id, { materialClass });
  if (s.status === "done" && s.result?.validation && !s.costRetrying && s.pricedWith !== materialClass) void retryPrices(id);
}

/** The 3D preview for a dropped copy of a saved part. Same bytes only; no check runs. */
export async function previewFromFile(file: File, key: string): Promise<{ ok: true; url: string; faceHash: string | null; faceSpace: "analysis" | "preview" } | { ok: false; error: string }> {
  const hash = await computeMeshHash(file).catch(() => null);
  if (!hash) return { ok: false, error: "This browser couldn't read the file." };
  if (hash !== key) return { ok: false, error: "That's a different file from this part's record (its fingerprint doesn't match)." };
  try {
    const pm = await fetchPreviewMesh(file, { forAnalysis: true, units: "mm" });
    if (!pm) return { ok: false, error: "The 3D preview couldn't be built from this file." };
    const blob = await fetch(pm.url).then((r) => r.blob()).catch(() => null);
    if (blob) void putCachedMesh({ hash: key, blob, faceHash: pm.faceHash, faceSpace: pm.faceSpace, filename: file.name, savedAt: Date.now() });
    return { ok: true, url: pm.url, faceHash: pm.faceHash, faceSpace: pm.faceSpace };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "The 3D preview couldn't be built." };
  }
}
