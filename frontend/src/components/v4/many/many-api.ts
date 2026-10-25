"use client";

/**
 * Reads the Many parts screens make beyond the shared helpers in lib/: the
 * makeability rollup and bucket rows in their real shape, the machine list,
 * a saved cost decision, and a lookup from analysis id to the part's bucket.
 * All same-origin through the authed proxy.
 */
import { API_BASE } from "@/lib/api-base";
import type { CostReport } from "@/lib/api";
import type { Machine, MakeRow } from "./makeability";

export class ManyApiError extends Error {
  readonly status: number;
  readonly code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ManyApiError";
    this.status = status;
    this.code = code;
  }
}

async function getJson<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  } catch {
    throw new ManyApiError("The server couldn’t be reached. Check your connection and try again.", 0);
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown; code?: string; message?: string } | null;
    const d = body?.detail;
    const code = (d && typeof d === "object" ? (d as { code?: string }).code : undefined) ?? body?.code;
    const msg =
      (d && typeof d === "object" ? (d as { message?: string }).message : typeof d === "string" ? d : undefined) ??
      body?.message ??
      `Request failed (${res.status}).`;
    throw new ManyApiError(msg, res.status, code);
  }
  return res.json() as Promise<T>;
}

export interface Rollup {
  summary: Record<string, number | boolean> & { total: number; stale_count: number; stale: boolean };
  buckets: string[];
  cold_projection?: boolean;
  note?: string;
  stale_note?: string;
  evaluation_note?: string;
}

export interface RowPage {
  rows: MakeRow[];
  next_cursor: string | null;
}

export function fetchRollup(): Promise<Rollup> {
  return getJson<Rollup>("/catalog/makeability");
}

export function fetchBucket(bucket: string, cursor?: string | null, pageSize = 100): Promise<RowPage> {
  const q = new URLSearchParams({ bucket, page_size: String(pageSize) });
  if (cursor) q.set("cursor", cursor);
  return getJson<RowPage>(`/catalog/makeability?${q}`);
}

export function fetchUnlocked(process: string, gate: string | null, cursor?: string | null): Promise<RowPage> {
  const q = new URLSearchParams({ process, page_size: "50" });
  if (gate) q.set("gate", gate);
  if (cursor) q.set("cursor", cursor);
  return getJson<RowPage>(`/catalog/capability-investment?${q}`);
}

export async function fetchMachines(): Promise<Machine[]> {
  const r = await getJson<{ machines: Machine[] }>("/machine-inventory");
  return Array.isArray(r.machines) ? r.machines : [];
}

export interface SavedDecision {
  id: string;
  filename: string;
  mesh_hash: string;
  created_at: string;
  is_stale?: boolean;
  result: CostReport;
}

export function fetchCostDecision(id: string): Promise<SavedDecision> {
  return getJson<SavedDecision>(`/cost-decisions/${encodeURIComponent(id)}`);
}

/** At most this many drill-down pages per bucket for the batch lookup (500 rows each). */
const LOOKUP_PAGES = 4;

/**
 * analysis id → the part's bucket and row, over every non-empty bucket. A part's
 * row carries its latest analysis; the same file with the same processes reuses
 * that analysis, so a batch item matches its part by id.
 */
export async function fetchMakeLookup(): Promise<Map<string, { bucket: string; row: MakeRow }>> {
  const roll = await fetchRollup();
  const out = new Map<string, { bucket: string; row: MakeRow }>();
  const keys = (roll.buckets ?? []).filter((k) => typeof roll.summary[k] === "number" && (roll.summary[k] as number) > 0);
  await Promise.all(
    keys.map(async (bucket) => {
      let cursor: string | null = null;
      for (let i = 0; i < LOOKUP_PAGES; i++) {
        const page: RowPage = await fetchBucket(bucket, cursor, 500);
        for (const row of page.rows) {
          const id = row.analysis?.id;
          if (id) out.set(id, { bucket, row });
        }
        cursor = page.next_cursor;
        if (!cursor) break;
      }
    }),
  );
  return out;
}
