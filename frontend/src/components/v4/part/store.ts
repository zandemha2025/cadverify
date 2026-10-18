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
import type { AssemblyAnalysis, AssemblyModel } from "@/lib/verify/assembly";
import { retryVerificationCost, runVerification, type VerifyResult } from "@/lib/verify/run";
import { resolvedAnnualVolume } from "@/lib/verify/program-rollup";
import { putCachedMesh } from "./mesh-cache";
import { fetchAssemblyAnalysisV4, probeAssemblyV4 } from "./api";

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
  materialClass: string;
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
  emit();
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
    if (probe.kind === "refused") {
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
      { file, materialClass: s0.materialClass },
      {
        onValidation: ({ validation }) => {
          if (validation) patch(id, { validation, validatedAt: Date.now() });
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
  const open = !result.validation.geometry.is_watertight || !!result.costGeometryInvalid;
  patch(id, { result, validation: result.validation, key: result.meshHash ?? key, status: open ? "stopped" : "done", finishedAt: Date.now() });
}

/** Start the real check for a file. Returns the session id the pages subscribe to. */
export function startCheck(file: File, opts: { sample?: boolean; materialClass?: string } = {}): number {
  // A deliberate check gets its own allowance id; every request of it shares this File.
  const f = new File([file], file.name, { type: file.type, lastModified: file.lastModified });
  const id = nextId++;
  sessions.set(id, {
    id,
    file: f,
    sample: !!opts.sample,
    materialClass: opts.materialClass ?? "polymer",
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
  emit();
  void run(id);
  return id;
}

/** Retry only the prices; methods, findings and machine fit stay as they are. */
export async function retryPrices(id: number) {
  const s = sessions.get(id);
  if (!s?.result?.validation) return;
  patch(id, { costRetrying: true });
  try {
    const retried = await retryVerificationCost({ file: s.file, materialClass: s.materialClass }, s.result.machines, resolvedAnnualVolume(s.result.partContext));
    patch(id, (x) => ({ costRetrying: false, result: x.result ? { ...x.result, ...retried } : x.result }));
  } catch (e) {
    patch(id, (x) => ({ costRetrying: false, result: x.result ? { ...x.result, costError: e instanceof Error ? e.message : "Prices didn’t finish." } : x.result }));
  } finally {
    window.dispatchEvent(new Event("proofshape:usage-changed"));
  }
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
