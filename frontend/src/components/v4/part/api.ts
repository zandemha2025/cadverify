/**
 * Data access for the part pages. Reuses the app's API helpers; the few calls
 * those don't cover (a disposition naming the chosen route, the assembly probe
 * that keeps the product tree when the 3D view is a pilot tool) live here.
 * Every call goes through the same-origin authed proxy.
 */
import { API_BASE } from "@/lib/api-base";
import { isKeptJob } from "./kept-job-model";
import { waitForKeptJob } from "./kept-job";
import {
  fetchAnalysis,
  fetchCatalog,
  fetchCostDecision,
  fetchCostDecisions,
  type CatalogRowApi,
  type CostDecisionDetail,
  type CostDecisionSummary,
  type CostDispositionResult,
  type CostReport,
  type ValidationResult,
} from "@/lib/api";
import { apiProblemDetail, apiRecoveryMessage, refusalDetail } from "@/lib/api-recovery";
import { listMachines, type OwnedMachine } from "@/lib/verify/machine-api";
import { fetchPartContext, type PartContext } from "@/lib/verify/part-context-read";
import { partCheckHeaders } from "@/lib/verify/check-id";
import { KNOWN_ENGINE_PROCESSES } from "@/lib/verify/run";
import type { AssemblyAnalysis, AssemblyModel } from "@/lib/verify/assembly";
import type { Disposition } from "./model";
import { getCachedMesh, putCachedMesh } from "./mesh-cache";

export interface SavedPart {
  decisions: CostDecisionSummary[];
  hasMore: boolean;
  latest: CostDecisionDetail | null;
  latestError: string | null;
  catalog: CatalogRowApi | null;
  validation: ValidationResult | null;
  analysisId: string | null;
  context: PartContext | null;
  machines: OwnedMachine[];
}

function msg(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

/** Everything saved about one part (by mesh hash): its records, the analysis, its context. */
export async function loadSavedPart(key: string): Promise<SavedPart> {
  const [page, catalog, context, machines] = await Promise.all([
    fetchCostDecisions({ meshHash: key, limit: 50 }),
    fetchCatalog({ partKey: key, pageSize: 1 }).then((p) => p.rows.find((r) => r.part_key === key) ?? null).catch(() => null),
    fetchPartContext(key).then((r) => r.context).catch(() => null),
    listMachines().then((p) => p.machines).catch(() => [] as OwnedMachine[]),
  ]);
  const decisions = page.cost_decisions ?? [];
  let latest: CostDecisionDetail | null = null;
  let latestError: string | null = null;
  if (decisions[0]) {
    try {
      latest = await fetchCostDecision(decisions[0].id);
    } catch (e) {
      latestError = msg(e, "The saved record didn't load.");
    }
  }
  let validation: ValidationResult | null = null;
  const analysisId = catalog?.analysis?.id ?? null;
  if (analysisId) {
    try {
      validation = (await fetchAnalysis(analysisId)).result_json;
    } catch {
      validation = null;
    }
  }
  return { decisions, hasMore: !!page.has_more, latest, latestError, catalog, validation, analysisId, context, machines };
}

export async function reloadDecision(id: string): Promise<CostDecisionDetail> {
  return fetchCostDecision(id);
}

export async function putDisposition(
  id: string,
  body: { disposition: Disposition | null; note?: string | null; quantity?: number; process?: string; material?: string },
): Promise<CostDispositionResult> {
  const payload: Record<string, unknown> = { disposition: body.disposition, note: body.disposition ? body.note?.trim() || null : null };
  if (body.disposition && body.quantity != null) payload.quantity = body.quantity;
  if (body.disposition && body.process) {
    payload.process = body.process;
    if (body.material) payload.material = body.material;
  }
  const res = await fetch(`${API_BASE}/cost-decisions/${encodeURIComponent(id)}/disposition`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(apiProblemDetail(data) ?? apiRecoveryMessage({ status: res.status, payload: data, resource: "decision" }));
  return data as CostDispositionResult;
}

/* ── re-check from the kept source ──────────────────────────────────────── */

export interface StoredRecheck {
  cost: CostReport;
  /** What the server re-checked: the kept file and the inputs it used. */
  recheck: { filename: string; qty: string; material_class: string; checks_used: number; basis: Record<string, string> };
}

/** A re-check the server refused, with whether it was the free-account ceiling. */
export class RecheckError extends Error {
  constructor(message: string, readonly status: number, readonly limit: boolean) {
    super(message);
  }
}

/**
 * POST /parts/{hash}/recheck: the same price as an upload, from the file the
 * organization kept (no upload, no check). Saved like an upload, so reloading
 * the part shows it. `owned`: the org's machines' processes (unknown ones are
 * dropped, as a fresh check does).
 */
export async function recheckStored(key: string, opts: { materialClass?: string | null; qty?: number[]; owned?: string[]; orientation?: string | null; onWorker?: (stage: string) => void }): Promise<StoredRecheck> {
  const q = new URLSearchParams();
  if (opts.materialClass) q.set("material_class", opts.materialClass);
  if (opts.qty?.length) q.set("qty", opts.qty.join(","));
  const owned = (opts.owned ?? []).filter((p) => KNOWN_ENGINE_PROCESSES.has(p));
  if (owned.length) q.set("owned_processes", owned.join(","));
  if (opts.orientation) q.set("orientation", opts.orientation);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/parts/${encodeURIComponent(key)}/recheck${q.toString() ? `?${q}` : ""}`, { method: "POST" });
  } catch {
    throw new RecheckError("The re-check couldn’t reach the server. Try again.", 0, false);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const d = (body as { detail?: { code?: string; message?: string } } | null)?.detail;
    if (res.status === 429 && d?.code === "free_tool_limit" && d.message) throw new RecheckError(`${d.message} Pro and Pilot plans don’t have this limit.`, 429, true);
    if (res.status === 404) throw new RecheckError("This part’s file isn’t kept with the record. Drop the file on the part to re-check it.", 404, false);
    throw new RecheckError(apiProblemDetail(body) ?? apiRecoveryMessage({ status: res.status, payload: body, resource: "re-check" }), res.status, false);
  }
  // A large kept file is re-priced on ScaleCAD's worker: the answer is the job (202), followed to its end.
  if (res.status === 202 && isKeptJob(body)) {
    try {
      const r = await waitForKeptJob<CostReport & { recheck: StoredRecheck["recheck"] }>(body, opts.onWorker);
      if (!r?.recheck) throw new RecheckError("The re-check finished without a readable answer. Reload the part to see what was saved.", 0, false);
      return { cost: r, recheck: r.recheck };
    } catch (e) {
      if (e instanceof RecheckError) throw e;
      throw new RecheckError(e instanceof Error ? e.message : "The re-check didn’t finish on the worker. Nothing was charged.", 0, false);
    }
  }
  const b = body as (CostReport & { recheck: StoredRecheck["recheck"] }) | null;
  if (!b) throw new RecheckError("The re-check answered with nothing readable. Try again.", res.status, false);
  return { cost: b, recheck: b.recheck };
}

/* ── the part's kept source, in 3D ──────────────────────────────────────── */

/** Is the exact uploaded file kept with the record in this organization? null when it couldn't be asked. */
export async function fetchSourceKept(key: string): Promise<boolean | null> {
  try {
    const res = await fetch(`${API_BASE}/parts/${encodeURIComponent(key)}/source-status`, { cache: "no-store" });
    if (res.status === 404) return false;
    if (!res.ok) return null;
    const body = (await res.json().catch(() => null)) as { kept?: unknown } | null;
    return body?.kept === true;
  } catch {
    return null;
  }
}

export interface PartMesh {
  blob: Blob;
  faceHash: string | null;
  faceSpace: "analysis" | "preview";
  /** cache: this browser's copy · stored: built on the server from the kept source file */
  origin: "cache" | "stored";
}

/**
 * 3D for a saved part: this browser's copy first, else the organization's kept
 * source tessellated on the server (the same analysis face space as a check), which
 * is then kept in this browser too. Opening it never uses a check.
 */
export async function loadPartMesh(key: string, filename: string | null, onKept?: (kept: boolean | null) => void): Promise<{ mesh: PartMesh | null; kept: boolean | null; error: string | null }> {
  const [cached, kept] = await Promise.all([getCachedMesh(key), fetchSourceKept(key)]);
  // Whether the file is kept is known now; the 3D (possibly megabytes on a phone) can follow.
  onKept?.(kept);
  if (cached) return { mesh: { blob: cached.blob, faceHash: cached.faceHash, faceSpace: cached.faceSpace, origin: "cache" }, kept, error: null };
  if (kept !== true) return { mesh: null, kept, error: null };
  try {
    const res = await fetch(`${API_BASE}/parts/${encodeURIComponent(key)}/preview.glb?units=mm`, { cache: "no-store" });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      if (res.status === 404) return { mesh: null, kept: false, error: null };
      return { mesh: null, kept, error: apiProblemDetail(body) ?? apiRecoveryMessage({ status: res.status, payload: body, resource: "3D view" }) };
    }
    const blob = await res.blob();
    if (!blob.size) return { mesh: null, kept, error: "The 3D view of the kept file came back empty." };
    const faceHash = res.headers.get("x-mesh-face-hash");
    const faceSpace = res.headers.get("x-mesh-face-space") === "analysis" ? "analysis" : "preview";
    void putCachedMesh({ hash: key, blob, faceHash, faceSpace, filename: filename ?? "", savedAt: Date.now() });
    return { mesh: { blob, faceHash, faceSpace, origin: "stored" }, kept, error: null };
  } catch {
    return { mesh: null, kept, error: "The 3D view of the kept file couldn't reach the server." };
  }
}

/* ── assemblies ─────────────────────────────────────────────────────────── */

export type AssemblyProbeV4 =
  | { kind: "single" }
  | { kind: "assembly"; model: AssemblyModel; glbUrl: string | null; gate: "pilot" | null; glbError: string | null }
  | { kind: "refused"; title: string; detail: string; retry: boolean; status: number | null };

async function post(file: File, format: "json" | "glb" | "analysis"): Promise<Response | null> {
  const form = new FormData();
  form.append("file", file);
  try {
    return await fetch(`${API_BASE}/validate/assembly?format=${format}`, { method: "POST", headers: partCheckHeaders(file), body: form });
  } catch {
    return null;
  }
}

function paidGate(body: unknown): boolean {
  const b = body as { code?: unknown; detail?: { code?: unknown } } | null;
  return b?.code === "paid_access_required" || b?.detail?.code === "paid_access_required";
}

/** Is this STEP/IGES file several bodies? Keeps the product tree even when the 3D view is gated. */
export async function probeAssemblyV4(file: File): Promise<AssemblyProbeV4> {
  const json = await post(file, "json");
  if (!json) return { kind: "refused", title: "Couldn't reach the server", detail: "Check the connection and try again. Nothing was checked.", retry: true, status: null };
  const body = await json.json().catch(() => null);
  // The assembly view is a pilot tool: on other plans the file is checked as one
  // file, and its bodies are read one by one on the part page.
  if (json.status === 403 && paidGate(body)) return { kind: "single" };
  if (!json.ok) {
    return {
      kind: "refused",
      title: json.status >= 500 || json.status === 429 ? "The check couldn't start" : "Can't read this file",
      // Out of checks or a phone check first must read as that, not as an unreadable file.
      detail: refusalDetail(json.status, body, "verification"),
      retry: json.status >= 500 || json.status === 429,
      status: json.status,
    };
  }
  const model = body as AssemblyModel | null;
  if (!model || !Array.isArray(model.parts)) return { kind: "refused", title: "Can't read this file", detail: "The assembly reader returned nothing usable. Try again.", retry: true, status: json.status };
  if (model.kind !== "assembly" || model.part_count < 2) return { kind: "single" };
  const glb = await post(file, "glb");
  if (!glb) return { kind: "assembly", model, glbUrl: null, gate: null, glbError: "The 3D view couldn't reach the server." };
  if (!glb.ok) {
    const gb = await glb.json().catch(() => null);
    return { kind: "assembly", model, glbUrl: null, gate: paidGate(gb) ? "pilot" : null, glbError: paidGate(gb) ? null : apiProblemDetail(gb) ?? "The 3D view couldn't be built." };
  }
  const blob = await glb.blob().catch(() => null);
  if (!blob || !blob.size) return { kind: "assembly", model, glbUrl: null, gate: null, glbError: "The 3D view came back empty." };
  return { kind: "assembly", model, glbUrl: URL.createObjectURL(blob), gate: null, glbError: null };
}

export async function fetchAssemblyAnalysisV4(file: File): Promise<{ analysis: AssemblyAnalysis | null; gate: "pilot" | null; error: string | null }> {
  const res = await post(file, "analysis");
  if (!res) return { analysis: null, gate: null, error: "The analysis couldn't reach the server." };
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (paidGate(body)) return { analysis: null, gate: "pilot", error: null };
    return { analysis: null, gate: null, error: apiProblemDetail(body) ?? apiRecoveryMessage({ status: res.status, payload: body, resource: "assembly analysis" }) };
  }
  return { analysis: (body as { analysis?: AssemblyAnalysis } | null)?.analysis ?? null, gate: null, error: null };
}
