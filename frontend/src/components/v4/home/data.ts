/**
 * Reads for Home, Parts and Setup. Same-origin through the authed proxy
 * (`API_BASE`). A short in-memory cache lets Home → Parts → Home reuse what was
 * just loaded instead of hitting rate-limited endpoints again; Retry bypasses it.
 * Errors carry the server's own message when it sent one.
 */
import { API_BASE } from "@/lib/api-base";
import { BUCKETS, type Bucket, type ChangeRow, type MachineRow, type MakeRow, type MakeSummary, type PartRow, type Posture, type RateSource, type RecordRow } from "./model";

const TTL = 30_000;
const cache = new Map<string, { at: number; p: Promise<unknown> }>();

export class LoadError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body && (body.detail ?? body.message ?? body.title);
    const msg = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `The server answered ${res.status}`;
    throw new LoadError(msg, res.status);
  }
  return res.json() as Promise<T>;
}

/** Cached GET. `fresh` skips (and replaces) the cached copy. A failed load is never cached. */
export function load<T>(path: string, fresh = false): Promise<T> {
  const hit = cache.get(path);
  if (!fresh && hit && Date.now() - hit.at < TTL) return hit.p as Promise<T>;
  const p = getJson<T>(path);
  cache.set(path, { at: Date.now(), p });
  p.catch(() => {
    if (cache.get(path)?.p === p) cache.delete(path);
  });
  return p;
}

export function forget(prefix: string): void {
  for (const k of cache.keys()) if (k.startsWith(prefix)) cache.delete(k);
}

export function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "The server didn't answer.";
}

export interface CatalogPage {
  rows: PartRow[];
  pagination: { page: number; page_size: number; total: number; total_pages: number; has_more: boolean };
  facets: { state: Record<string, number>; route: Record<string, number>; findings: { with_findings: number; without_findings: number; unknown: number } };
  truncated: boolean;
}

export const CATALOG_PAGE = 100;

export function catalogPage(page: number, fresh = false): Promise<CatalogPage> {
  return load<CatalogPage>(`/catalog?page=${page}&page_size=${CATALOG_PAGE}`, fresh);
}

export function catalogTotal(f: CatalogPage["facets"]): number {
  return Object.values(f.state).reduce((a, b) => a + b, 0);
}

export function makeRollup(fresh = false): Promise<{ summary: MakeSummary; note?: string; cold_projection?: boolean }> {
  return load(`/catalog/makeability`, fresh);
}

/** One bucket's parts, first keyset page (500 max). `more` says whether the bucket had more. */
export async function makeBucket(bucket: Bucket, fresh = false): Promise<{ rows: MakeRow[]; more: boolean }> {
  const b = await load<{ rows: MakeRow[]; next_cursor: string | null }>(`/catalog/makeability?bucket=${bucket}&page_size=500`, fresh);
  return { rows: b.rows ?? [], more: Boolean(b.next_cursor) };
}

/** The makeability block for every part in the non-empty buckets (the rollup says which). */
export async function makeIndex(summary: MakeSummary, fresh = false): Promise<{ byPart: Map<string, MakeRow>; partial: boolean }> {
  const want = BUCKETS.filter((b) => (summary[b] ?? 0) > 0);
  const pages = await Promise.all(want.map((b) => makeBucket(b, fresh)));
  const byPart = new Map<string, MakeRow>();
  let partial = false;
  for (const p of pages) {
    partial ||= p.more;
    for (const r of p.rows) byPart.set(r.part_key, r);
  }
  return { byPart, partial };
}

export function records(fresh = false): Promise<{ cost_decisions: RecordRow[]; has_more: boolean }> {
  return load(`/cost-decisions?limit=100`, fresh);
}

export function machines(fresh = false): Promise<MachineRow[]> {
  return load<{ machines?: MachineRow[] } | MachineRow[]>(`/machine-inventory`, fresh).then((b) => (Array.isArray(b) ? b : (b.machines ?? [])));
}

export function changes(fresh = false): Promise<ChangeRow[]> {
  return load<{ change_requests: ChangeRow[] }>(`/governance/change-requests`, fresh).then((b) => b.change_requests ?? []);
}

/** Real (not stand-in) actual-cost records. */
export function actualCount(fresh = false): Promise<number> {
  return load<{ records: { stand_in?: boolean }[] }>(`/ground-truth`, fresh).then((b) => (b.records ?? []).filter((r) => !r.stand_in).length);
}

export interface PortfolioLite {
  summary: { parts: number; costed: number; posture?: Posture; programs?: { program: string }[] };
  rows: { part_key: string; context?: { program?: string | null; annual_volume?: number | null } | null; resolved_annual_volume?: number | null }[];
}

export function portfolio(fresh = false): Promise<PortfolioLite> {
  return load(`/catalog/portfolio`, fresh);
}

/** Declared programs and parts with a yearly volume, from the portfolio rows. */
export function programFacts(p: PortfolioLite): { programs: number; withVolume: number; inProgram: number } {
  const names = new Set<string>();
  for (const s of p.summary.programs ?? []) names.add(s.program);
  let withVolume = 0;
  let inProgram = 0;
  for (const r of p.rows) {
    const prog = r.context?.program;
    if (prog) {
      names.add(prog);
      inProgram += 1;
    }
    const vol = r.resolved_annual_volume ?? r.context?.annual_volume ?? null;
    if (vol != null && vol > 0) withVolume += 1;
  }
  return { programs: names.size, withVolume, inProgram };
}

export function rateSource(fresh = false): Promise<RateSource> {
  return load(`/rate-library/effective`, fresh);
}

export interface OrgInfo {
  id: string | null;
  name: string | null;
  role: string | null;
}

export function org(fresh = false): Promise<OrgInfo> {
  return load<{ active_org_id: string | null; organizations: { org_id: string; name: string; org_role: string }[] }>(`/orgs`, fresh).then((b) => {
    const a = b.organizations?.find((o) => o.org_id === b.active_org_id) ?? b.organizations?.[0] ?? null;
    return { id: a?.org_id ?? null, name: a?.name ?? null, role: a?.org_role ?? null };
  });
}

export function members(fresh = false): Promise<{ email: string; org_role: string; is_active: boolean }[]> {
  return load<{ members: { email: string; org_role: string; is_active: boolean }[] }>(`/orgs/members`, fresh).then((b) => b.members ?? []);
}

export function librarySize(fresh = false): Promise<number> {
  return load<{ library_size: number }>(`/identity/library`, fresh).then((b) => b.library_size);
}
