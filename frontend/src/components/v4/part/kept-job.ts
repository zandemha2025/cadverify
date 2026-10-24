"use client";

/**
 * Follow a big kept part's re-price or repair on ScaleCAD's worker until it
 * ends, keeping the work bar's line for it current on every page, then hand
 * back the response its route would have given (GET /checks/{id} ``result``).
 * The job runs on the server whatever this tab does; a slow or dropped poll
 * never ends the watch.
 */
import { API_BASE } from "@/lib/api-base";
import { markWorkSeen, registerWork } from "../work/work-bar";
import { keptWorkLine, type KeptJobStatus } from "./kept-job-model";

export class KeptJobError extends Error {
  readonly code: string | null;
  constructor(message: string, code: string | null) {
    super(message);
    this.name = "KeptJobError";
    this.code = code;
  }
}

const workKey = (checkId: string) => `stored:${checkId}`;

function show(s: KeptJobStatus) {
  const line = keptWorkLine(s);
  registerWork({ key: workKey(s.check_id), persist: true, ...line });
}

async function read(checkId: string): Promise<KeptJobStatus> {
  const res = await fetch(`${API_BASE}/checks/${encodeURIComponent(checkId)}`, { cache: "no-store", signal: AbortSignal.timeout(15_000) });
  if (!res.ok) throw new Error(`job ${res.status}`);
  return (await res.json()) as KeptJobStatus;
}

/** Wait for the job; ``onStage`` hears each new stage. Resolves with the route's response. */
export async function waitForKeptJob<T>(first: KeptJobStatus, onStage?: (stage: string) => void): Promise<T> {
  show(first);
  onStage?.(first.stage);
  let last = first.stage;
  for (let misses = 0; ; ) {
    await new Promise((r) => setTimeout(r, misses ? Math.min(30_000, 3000 * misses) : 2500));
    let s: KeptJobStatus;
    try {
      s = await read(first.check_id);
      misses = 0;
    } catch {
      misses += 1;
      continue;
    }
    show(s);
    if (s.stage !== last) {
      last = s.stage;
      onStage?.(s.stage);
    }
    if (s.status === "done") {
      // Seen where it was asked for: the part page that is waiting for it.
      if (typeof window !== "undefined" && s.mesh_hash && window.location.pathname.includes(s.mesh_hash)) markWorkSeen(workKey(s.check_id));
      return s.result as T;
    }
    if (s.status === "failed") throw new KeptJobError(s.error?.message ?? "It didn’t finish on the worker. Nothing was charged.", s.error?.code ?? null);
  }
}
