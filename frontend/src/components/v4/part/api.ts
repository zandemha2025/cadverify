/**
 * Data access for the part pages. Reuses the app's API helpers; the few calls
 * those don't cover (a disposition naming the chosen route, the assembly probe
 * that keeps the product tree when the 3D view is a pilot tool) live here.
 * Every call goes through the same-origin authed proxy.
 */
import { API_BASE } from "@/lib/api-base";
import {
  fetchAnalysis,
  fetchCatalog,
  fetchCostDecision,
  fetchCostDecisions,
  type CatalogRowApi,
  type CostDecisionDetail,
  type CostDecisionSummary,
  type CostDispositionResult,
  type ValidationResult,
} from "@/lib/api";
import { apiProblemDetail, apiRecoveryMessage } from "@/lib/api-recovery";
import { listMachines, type OwnedMachine } from "@/lib/verify/machine-api";
import { fetchPartContext, type PartContext } from "@/lib/verify/part-context-read";
import { partCheckHeaders } from "@/lib/verify/check-id";
import type { AssemblyAnalysis, AssemblyModel } from "@/lib/verify/assembly";
import type { Disposition } from "./model";

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
  if (!json.ok) {
    return {
      kind: "refused",
      title: json.status >= 500 || json.status === 429 ? "The check couldn't start" : "Can't read this file",
      detail: apiProblemDetail(body) ?? apiRecoveryMessage({ status: json.status, payload: body, resource: "verification" }),
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
