/**
 * An assembly's 3D view (POST /validate/assembly?format=glb) and per-part analysis
 * (?format=analysis), with the same busy handling as a single part's calls (busy.ts):
 * a busy server is asked again by itself, honouring Retry-After, for up to about three
 * minutes, with each wait reported for the countdown; still busy after that, or stopped
 * on ScaleCAD's side (a 5xx, no answer), each comes back as such, never as the file's
 * fault. The request itself is passed in (`post`), so this stays testable in node.
 */
import { BUSY_BOUND_MS, busySignal, retryWhileBusy, serverTrouble, type BusyAttempt, type BusyKind, type RetryWhileBusyOptions } from "../../../lib/verify/busy.ts";
import { apiProblemDetail, apiRecoveryMessage } from "../../../lib/api-recovery.ts";
import type { AssemblyAnalysis } from "@/lib/verify/assembly";

/** One POST of the file in that format; null when no answer came back. */
export type PostAssembly = (format: "glb" | "analysis") => Promise<Response | null>;

export type AssemblyWaitOptions = Pick<RetryWhileBusyOptions, "onWait" | "boundMs" | "now" | "sleep" | "random">;

export interface StillBusyLike {
  kind: BusyKind;
  waitedMs: number;
}

export interface AssemblyGlbOut {
  glbUrl: string | null;
  gate: "pilot" | null;
  /** A refusal the 3D view can't get past (the server's own words); null otherwise. */
  glbError: string | null;
  /** Stopped on ScaleCAD's side: its status (0: no answer). */
  server: number | null;
  /** Still busy after the waiting. */
  stillBusy: StillBusyLike | null;
}

export interface AssemblyAnalysisOut {
  analysis: AssemblyAnalysis | null;
  gate: "pilot" | null;
  error: string | null;
  /** The status of a failed analysis (0: no answer), so the page can tell ScaleCAD's side from a refusal. */
  status: number | null;
  stillBusy: StillBusyLike | null;
}

export function paidGate(body: unknown): boolean {
  const b = body as { code?: unknown; detail?: { code?: unknown } } | null;
  return b?.code === "paid_access_required" || b?.detail?.code === "paid_access_required";
}

function stillBusy(busy: { kind: BusyKind }, since: number, now: () => number): StillBusyLike {
  return { kind: busy.kind, waitedMs: now() - since };
}

/** The assembly's 3D view, waiting out a busy server. `objectUrl` turns the GLB into a URL for the viewer. */
export async function assemblyGlb(post: PostAssembly, opts: AssemblyWaitOptions = {}, objectUrl: (b: Blob) => string = (b) => URL.createObjectURL(b)): Promise<AssemblyGlbOut> {
  const empty = { glbUrl: null, gate: null, glbError: null, server: null, stillBusy: null };
  const once = async (): Promise<BusyAttempt<AssemblyGlbOut>> => {
    const res = await post("glb");
    if (!res) return { value: { ...empty, server: 0 } };
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      const busy = busySignal(res.status, body, res.headers.get("retry-after"));
      if (busy) return { busy };
      if (paidGate(body)) return { value: { ...empty, gate: "pilot" } };
      if (serverTrouble(res.status)) return { value: { ...empty, server: res.status } };
      return { value: { ...empty, glbError: apiProblemDetail(body) ?? "The 3D view couldn't be built." } };
    }
    const blob = await res.blob().catch(() => null);
    if (!blob || !blob.size) return { value: { ...empty, glbError: "The 3D view came back empty." } };
    return { value: { ...empty, glbUrl: objectUrl(blob) } };
  };
  const now = opts.now ?? Date.now;
  const out = await retryWhileBusy(once, { boundMs: BUSY_BOUND_MS, ...opts });
  return out.ok ? out.value : { ...empty, stillBusy: stillBusy(out.busy, out.since, now) };
}

/** The per-part analysis (DFM, cost, interference), waiting out a busy server. */
export async function assemblyAnalysis(post: PostAssembly, opts: AssemblyWaitOptions = {}): Promise<AssemblyAnalysisOut> {
  const empty = { analysis: null, gate: null, error: null, status: null, stillBusy: null };
  const once = async (): Promise<BusyAttempt<AssemblyAnalysisOut>> => {
    const res = await post("analysis");
    if (!res) return { value: { ...empty, error: "The analysis couldn't reach the server.", status: 0 } };
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      const busy = busySignal(res.status, body, res.headers.get("retry-after"));
      if (busy) return { busy };
      if (paidGate(body)) return { value: { ...empty, gate: "pilot" } };
      return {
        value: { ...empty, status: res.status, error: apiProblemDetail(body) ?? apiRecoveryMessage({ status: res.status, payload: body, resource: "assembly analysis" }) },
      };
    }
    return { value: { ...empty, analysis: (body as { analysis?: AssemblyAnalysis } | null)?.analysis ?? null } };
  };
  const now = opts.now ?? Date.now;
  const out = await retryWhileBusy(once, { boundMs: BUSY_BOUND_MS, ...opts });
  return out.ok ? out.value : { ...empty, stillBusy: stillBusy(out.busy, out.since, now) };
}
