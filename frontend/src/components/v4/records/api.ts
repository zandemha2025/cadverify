"use client";

/**
 * Reads and writes for Records, Compare, Analyses, Supplier packages and
 * Programs. Same-origin through the authed proxy (`API_BASE`).
 *
 * The record and analysis lists are rate-limited server-side (60 an hour), so
 * one shared, paged copy of each list lives here for the whole session: Records,
 * Compare and Supplier packages read the same records; a write patches the copy
 * instead of reloading. Retry and "Load more" are the only extra reads. A
 * record's engine result never changes, so a loaded record is kept too (its
 * approval and outcome are patched from each write's response).
 */
import * as React from "react";
import { API_BASE } from "@/lib/api-base";
import type {
  CostDecisionDetail,
  CostDecisionGovernance,
  CostDecisionSummary,
  RepairResult,
  RfqPackageDetail,
  RfqPackageSummary,
  ValidationResult,
} from "@/lib/api";
import type { AnalysisListRow } from "@/lib/recent-parts";
import type { Portfolio, PortfolioDelta } from "@/lib/verify/program-rollup";
import { applyPortfolioDelta } from "@/lib/verify/program-rollup";

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function detailText(body: unknown, status: number): string {
  const b = body as { detail?: unknown; message?: unknown; title?: unknown } | null;
  const d = b?.detail;
  if (typeof d === "string" && d.trim()) return d;
  if (d && typeof d === "object") {
    const m = (d as { message?: unknown }).message;
    if (typeof m === "string" && m.trim()) return m;
  }
  if (typeof b?.message === "string" && b.message.trim() && b.message !== "Not Found") return b.message;
  if (status === 404) return "Not found.";
  if (status === 403) return "Your role can't do this. Ask an admin.";
  if (status === 429) return "Too many requests for now. Wait a few minutes and retry.";
  if (status >= 500) return "The server had a problem. Retry in a moment.";
  return `The server answered ${status}.`;
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError("The server couldn't be reached. Check your connection and retry.", 0);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(detailText(body, res.status), res.status);
  }
  return res;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init);
  return (await res.json()) as T;
}

function body(method: string, payload: unknown): RequestInit {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(payload) };
}

export function errorText(e: unknown, fallback = "That didn't work."): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

/** Hand a blob to the browser as a download. */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function stem(filename: string): string {
  return filename.replace(/\.[^.]+$/, "") || "record";
}

/* ── a tiny shared store ────────────────────────────────────────────────── */

function store<S>(initial: S) {
  let state = initial;
  const subs = new Set<() => void>();
  return {
    get: () => state,
    set: (next: S | ((s: S) => S)) => {
      state = typeof next === "function" ? (next as (s: S) => S)(state) : next;
      subs.forEach((f) => f());
    },
    subscribe: (f: () => void) => {
      subs.add(f);
      return () => {
        subs.delete(f);
      };
    },
  };
}

function useStore<S>(s: ReturnType<typeof store<S>>): S {
  return React.useSyncExternalStore(s.subscribe, s.get, s.get);
}

/* ── records (cost decisions) ───────────────────────────────────────────── */

export const RECORD_PAGE = 50;

export interface ListState<T> {
  rows: T[] | null;
  error: string | null;
  more: boolean;
  cursor: string | null;
  loading: boolean;
  loadingMore: boolean;
  moreError: string | null;
}

const emptyList = <T,>(): ListState<T> => ({ rows: null, error: null, more: false, cursor: null, loading: false, loadingMore: false, moreError: null });

const recordList = store<ListState<CostDecisionSummary>>(emptyList());

async function loadRecords(): Promise<void> {
  if (recordList.get().loading) return;
  recordList.set((s) => ({ ...s, loading: true, error: null }));
  try {
    const p = await json<{ cost_decisions: CostDecisionSummary[]; next_cursor: string | null; has_more: boolean }>(`/cost-decisions?limit=${RECORD_PAGE}`);
    recordList.set({ ...emptyList(), rows: p.cost_decisions, cursor: p.next_cursor, more: p.has_more });
  } catch (e) {
    recordList.set((s) => ({ ...s, loading: false, error: errorText(e, "Records didn't load.") }));
  }
}

async function moreRecords(): Promise<void> {
  const s = recordList.get();
  if (!s.cursor || s.loadingMore) return;
  recordList.set({ ...s, loadingMore: true, moreError: null });
  try {
    const p = await json<{ cost_decisions: CostDecisionSummary[]; next_cursor: string | null; has_more: boolean }>(`/cost-decisions?limit=${RECORD_PAGE}&cursor=${encodeURIComponent(s.cursor)}`);
    recordList.set((x) => {
      const seen = new Set((x.rows ?? []).map((r) => r.id));
      return { ...x, rows: [...(x.rows ?? []), ...p.cost_decisions.filter((r) => !seen.has(r.id))], cursor: p.next_cursor, more: p.has_more, loadingMore: false };
    });
  } catch (e) {
    recordList.set((x) => ({ ...x, loadingMore: false, moreError: errorText(e, "More records didn't load.") }));
  }
}

/** The shared record list. Loads once per session; `reload` is Retry. */
export function useRecordList() {
  const s = useStore(recordList);
  React.useEffect(() => {
    const now = recordList.get();
    if (now.rows === null && !now.loading && !now.error) void loadRecords();
  }, []);
  return { ...s, reload: loadRecords, loadMore: moreRecords };
}

/** Patch one record in the shared list (after a write), or add it when it's missing. */
function patchRecordRow(id: string, patch: Partial<CostDecisionSummary>): void {
  recordList.set((s) => (s.rows ? { ...s, rows: s.rows.map((r) => (r.id === id ? { ...r, ...patch } : r)) } : s));
}

type DetailState = { detail: CostDecisionDetail | null; error: string | null; status: number; loading: boolean };
const details = store<Record<string, DetailState>>({});

async function loadDetail(id: string): Promise<void> {
  details.set((m) => ({ ...m, [id]: { detail: m[id]?.detail ?? null, error: null, status: 0, loading: true } }));
  try {
    const d = await json<CostDecisionDetail>(`/cost-decisions/${encodeURIComponent(id)}`);
    details.set((m) => ({ ...m, [id]: { detail: d, error: null, status: 200, loading: false } }));
  } catch (e) {
    const status = e instanceof ApiError ? e.status : 0;
    details.set((m) => ({ ...m, [id]: { detail: null, error: errorText(e, "The record didn't load."), status, loading: false } }));
  }
}

/** One record with its full result. Loaded once; Retry reloads. */
export function useRecord(id: string | null) {
  const all = useStore(details);
  React.useEffect(() => {
    if (!id) return;
    const s = details.get()[id];
    if (!s || (!s.detail && !s.loading && !s.error)) void loadDetail(id);
  }, [id]);
  const s = id ? all[id] : undefined;
  return { detail: s?.detail ?? null, error: s?.error ?? null, notFound: s?.status === 404, loading: !!id && (!s || s.loading), retry: () => id && loadDetail(id) };
}

/** Several records at once (Compare). */
export function useRecords(ids: (string | null)[]) {
  const all = useStore(details);
  const key = ids.join(",");
  React.useEffect(() => {
    for (const id of key.split(",")) {
      if (!id) continue;
      const s = details.get()[id];
      if (!s || (!s.detail && !s.loading && !s.error)) void loadDetail(id);
    }
  }, [key]);
  return ids.map((id) => {
    const s = id ? all[id] : undefined;
    return { id, detail: s?.detail ?? null, error: s?.error ?? null, loading: !!id && (!s || s.loading), retry: () => id && loadDetail(id) };
  });
}

function applyGovernance(id: string, patch: Partial<CostDecisionGovernance> & { is_public?: boolean; share_url?: string | null }): void {
  details.set((m) => {
    const cur = m[id];
    return cur?.detail ? { ...m, [id]: { ...cur, detail: { ...cur.detail, ...patch } } } : m;
  });
  patchRecordRow(id, patch as Partial<CostDecisionSummary>);
}

export async function setOutcome(
  id: string,
  input: { disposition: string | null; note?: string; quantity?: number; process?: string; material?: string },
): Promise<void> {
  const payload: Record<string, unknown> = { disposition: input.disposition, note: input.disposition ? input.note?.trim() || null : null };
  if (input.disposition && input.quantity != null) payload.quantity = input.quantity;
  if (input.disposition && input.process) {
    payload.process = input.process;
    if (input.material) payload.material = input.material;
  }
  const res = await json<CostDecisionGovernance>(`/cost-decisions/${encodeURIComponent(id)}/disposition`, body("PUT", payload));
  applyGovernance(id, pickGovernance(res));
}

export async function approve(id: string, note: string): Promise<void> {
  const res = await json<CostDecisionGovernance>(`/cost-decisions/${encodeURIComponent(id)}/approve`, body("POST", { note: note.trim() || null }));
  applyGovernance(id, pickGovernance(res));
}

export async function reopen(id: string): Promise<void> {
  const res = await json<CostDecisionGovernance>(`/cost-decisions/${encodeURIComponent(id)}/approve`, { method: "DELETE" });
  applyGovernance(id, pickGovernance(res));
}

const GOV_KEYS: (keyof CostDecisionGovernance)[] = [
  "approval_status",
  "approved_by_user_id",
  "approved_at",
  "approval_note",
  "is_stale",
  "stale_at",
  "stale_reason",
  "user_disposition",
  "user_disposition_label",
  "disposition_note",
  "disposition_basis",
  "disposition_updated_at",
  "disposition_updated_by_user_id",
];

function pickGovernance(r: CostDecisionGovernance): Partial<CostDecisionGovernance> {
  const out: Record<string, unknown> = {};
  for (const k of GOV_KEYS) if (k in r) out[k] = r[k];
  return out as Partial<CostDecisionGovernance>;
}

export async function shareRecord(id: string): Promise<string> {
  const r = await json<{ share_url: string }>(`/cost-decisions/${encodeURIComponent(id)}/share`, { method: "POST" });
  applyGovernance(id, { is_public: true, share_url: r.share_url });
  return r.share_url;
}

export async function unshareRecord(id: string): Promise<void> {
  await send(`/cost-decisions/${encodeURIComponent(id)}/share`, { method: "DELETE" });
  applyGovernance(id, { is_public: false, share_url: null });
}

export async function exportRecord(id: string, filename: string, kind: "pdf" | "csv" | "json"): Promise<string> {
  const path = kind === "pdf" ? "pdf" : kind === "csv" ? "export.csv" : "export.json";
  const res = await send(`/cost-decisions/${encodeURIComponent(id)}/${path}`);
  const name = `${stem(filename)}-${kind === "pdf" ? "cost-report.pdf" : kind === "csv" ? "cost.csv" : "cost.json"}`;
  saveBlob(await res.blob(), name);
  return name;
}

/** Records of one part (exact mesh hash), newest first. */
export function recordsOfPart(meshHash: string): Promise<CostDecisionSummary[]> {
  return json<{ cost_decisions: CostDecisionSummary[] }>(`/cost-decisions?limit=50&mesh_hash=${encodeURIComponent(meshHash)}`).then((p) => p.cost_decisions ?? []);
}

/* ── org members (who approved) ─────────────────────────────────────────── */

let membersP: Promise<Map<number, string>> | null = null;

export function members(): Promise<Map<number, string>> {
  if (!membersP) {
    membersP = json<{ members: { user_id: number; email: string }[] }>(`/orgs/members`)
      .then((b) => new Map((b.members ?? []).map((m) => [m.user_id, m.email])))
      .catch(() => {
        membersP = null;
        return new Map<number, string>();
      });
  }
  return membersP;
}

export function useMembers(): Map<number, string> | null {
  const [m, setM] = React.useState<Map<number, string> | null>(null);
  React.useEffect(() => {
    let alive = true;
    void members().then((x) => alive && setM(x));
    return () => {
      alive = false;
    };
  }, []);
  return m;
}

/* ── the portfolio: part contexts (conditions, program, volume) ─────────── */

/**
 * The org portfolio (GET /catalog/portfolio): every costed part with its
 * declared context. Records read a part's conditions from it (one read, no
 * per-part lookups); Programs reads and patches it from each write's delta.
 */
type PortfolioState = { data: Portfolio | null; error: string | null; loading: boolean };
const portfolio = store<PortfolioState>({ data: null, error: null, loading: false });

export async function loadPortfolio(): Promise<void> {
  if (portfolio.get().loading) return;
  portfolio.set((s) => ({ ...s, loading: true, error: null }));
  try {
    const data = await json<Portfolio>(`/catalog/portfolio`);
    portfolio.set({ data, error: null, loading: false });
  } catch (e) {
    portfolio.set((s) => ({ ...s, loading: false, error: errorText(e, "Programs didn't load.") }));
  }
}

export function usePortfolio() {
  const s = useStore(portfolio);
  React.useEffect(() => {
    const now = portfolio.get();
    if (!now.data && !now.loading && !now.error) void loadPortfolio();
  }, []);
  return { ...s, reload: loadPortfolio };
}

export function patchPortfolio(meshHash: string, delta: PortfolioDelta | null): void {
  if (!delta) {
    void loadPortfolio();
    return;
  }
  portfolio.set((s) => (s.data ? { ...s, data: applyPortfolioDelta(s.data, meshHash, delta) } : s));
}

export interface PartCtx {
  program: string | null;
  annual_volume: number | null;
  service_environment?: Record<string, unknown> | null;
}

/** A part's declared context: undefined while loading, null when none is declared (or it couldn't be read). */
export function usePartContext(meshHash: string | null | undefined): PartCtx | null | undefined {
  const s = usePortfolio();
  if (!meshHash) return null;
  if (!s.data) return s.error ? null : undefined;
  const row = s.data.rows.find((r) => r.part_key === meshHash);
  return row?.context ?? null;
}

/* ── analyses ───────────────────────────────────────────────────────────── */

export const ANALYSIS_PAGE = 50;

const analysisList = store<ListState<AnalysisListRow>>(emptyList());

async function loadAnalyses(): Promise<void> {
  if (analysisList.get().loading) return;
  analysisList.set((s) => ({ ...s, loading: true, error: null }));
  try {
    const p = await json<{ analyses: AnalysisListRow[]; next_cursor: string | null; has_more: boolean }>(`/analyses?limit=${ANALYSIS_PAGE}`);
    analysisList.set({ ...emptyList(), rows: p.analyses, cursor: p.next_cursor, more: p.has_more });
  } catch (e) {
    analysisList.set((s) => ({ ...s, loading: false, error: errorText(e, "Analyses didn't load.") }));
  }
}

async function moreAnalyses(): Promise<void> {
  const s = analysisList.get();
  if (!s.cursor || s.loadingMore) return;
  analysisList.set({ ...s, loadingMore: true, moreError: null });
  try {
    const p = await json<{ analyses: AnalysisListRow[]; next_cursor: string | null; has_more: boolean }>(`/analyses?limit=${ANALYSIS_PAGE}&cursor=${encodeURIComponent(s.cursor)}`);
    analysisList.set((x) => {
      const seen = new Set((x.rows ?? []).map((r) => r.id));
      return { ...x, rows: [...(x.rows ?? []), ...p.analyses.filter((r) => !seen.has(r.id))], cursor: p.next_cursor, more: p.has_more, loadingMore: false };
    });
  } catch (e) {
    analysisList.set((x) => ({ ...x, loadingMore: false, moreError: errorText(e, "More analyses didn't load.") }));
  }
}

export function useAnalysisList() {
  const s = useStore(analysisList);
  React.useEffect(() => {
    const now = analysisList.get();
    if (now.rows === null && !now.loading && !now.error) void loadAnalyses();
  }, []);
  return { ...s, reload: loadAnalyses, loadMore: moreAnalyses };
}

/** The analysis detail as the API actually returns it (`result`, older builds `result_json`). */
export interface AnalysisFull {
  id: string;
  filename: string;
  file_type: string;
  verdict?: string;
  overall_verdict?: string;
  face_count: number;
  duration_ms?: number;
  analysis_time_ms?: number;
  created_at: string;
  is_public: boolean;
  share_url: string | null;
  result: ValidationResult & { analysis_mesh_hash?: string };
  decision_links: { id: string; url: string; filename: string; make_now_process: string | null; approval_status: string; created_at: string }[];
}

type AnalysisState = { detail: AnalysisFull | null; error: string | null; status: number; loading: boolean };
const analyses = store<Record<string, AnalysisState>>({});

async function loadAnalysis(id: string): Promise<void> {
  analyses.set((m) => ({ ...m, [id]: { detail: m[id]?.detail ?? null, error: null, status: 0, loading: true } }));
  try {
    const raw = await json<AnalysisFull & { result_json?: ValidationResult }>(`/analyses/${encodeURIComponent(id)}`);
    const d: AnalysisFull = { ...raw, result: (raw.result ?? raw.result_json) as AnalysisFull["result"], decision_links: raw.decision_links ?? [] };
    analyses.set((m) => ({ ...m, [id]: { detail: d, error: null, status: 200, loading: false } }));
  } catch (e) {
    const status = e instanceof ApiError ? e.status : 0;
    analyses.set((m) => ({ ...m, [id]: { detail: null, error: errorText(e, "The analysis didn't load."), status, loading: false } }));
  }
}

export function useAnalysis(id: string | null) {
  const all = useStore(analyses);
  React.useEffect(() => {
    if (!id) return;
    const s = analyses.get()[id];
    if (!s || (!s.detail && !s.loading && !s.error)) void loadAnalysis(id);
  }, [id]);
  const s = id ? all[id] : undefined;
  return { detail: s?.detail ?? null, error: s?.error ?? null, notFound: s?.status === 404, loading: !!id && (!s || s.loading), retry: () => id && loadAnalysis(id) };
}

function patchAnalysis(id: string, patch: Partial<AnalysisFull>): void {
  analyses.set((m) => {
    const cur = m[id];
    return cur?.detail ? { ...m, [id]: { ...cur, detail: { ...cur.detail, ...patch } } } : m;
  });
}

export async function shareAnalysis(id: string): Promise<string> {
  const r = await json<{ share_url: string }>(`/analyses/${encodeURIComponent(id)}/share`, { method: "POST" });
  patchAnalysis(id, { is_public: true, share_url: r.share_url });
  return r.share_url;
}

export async function unshareAnalysis(id: string): Promise<void> {
  await send(`/analyses/${encodeURIComponent(id)}/share`, { method: "DELETE" });
  patchAnalysis(id, { is_public: false, share_url: null });
}

export async function analysisPdf(id: string, filename: string): Promise<string> {
  const res = await send(`/analyses/${encodeURIComponent(id)}/pdf`);
  const name = `${stem(filename)}-dfm-report.pdf`;
  saveBlob(await res.blob(), name);
  return name;
}

/** Repair a copy of the file the user picks (the server re-checks the copy). */
export function repairFile(file: File): Promise<RepairResult> {
  const fd = new FormData();
  fd.append("file", file);
  return json<RepairResult>(`/validate/repair`, { method: "POST", body: fd });
}

/** The repaired copy as a File (for download or to check again). */
export function repairedFile(r: RepairResult, original: string): File | null {
  if (!r.repaired_file_b64) return null;
  const bin = atob(r.repaired_file_b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const name = r.repair_verification?.download_filename ?? `${stem(original)}-repaired.stl`;
  return new File([bytes], name, { type: r.repair_verification?.download_media_type ?? "model/stl" });
}

/* ── analysis → part key ────────────────────────────────────────────────── */

/**
 * The part an analysis belongs to. The analysis detail doesn't carry the part
 * key (its `analysis_mesh_hash` is a different digest), so read it from a linked
 * record in the shared record list, else from the catalog's latest analysis per
 * part (one cached read).
 */
let catalogP: Promise<Map<string, string>> | null = null;

function catalogIndex(): Promise<Map<string, string>> {
  if (!catalogP) {
    catalogP = json<{ rows: { part_key: string; analysis: { id: string } | null }[] }>(`/catalog?page_size=100`)
      .then((b) => new Map((b.rows ?? []).filter((r) => r.analysis?.id).map((r) => [r.analysis!.id, r.part_key])))
      .catch(() => {
        catalogP = null;
        return new Map<string, string>();
      });
  }
  return catalogP;
}

export function usePartKeyForAnalysis(analysisId: string, linkIds: string[]): string | null | undefined {
  const records = useStore(recordList);
  const fromRecords = linkIds.map((id) => records.rows?.find((r) => r.id === id)?.mesh_hash).find(Boolean) ?? null;
  const [fromCatalog, setFromCatalog] = React.useState<{ id: string; key: string | null } | null>(null);
  React.useEffect(() => {
    if (fromRecords) return;
    let alive = true;
    void catalogIndex().then((m) => alive && setFromCatalog({ id: analysisId, key: m.get(analysisId) ?? null }));
    return () => {
      alive = false;
    };
  }, [analysisId, fromRecords]);
  if (fromRecords) return fromRecords;
  return fromCatalog && fromCatalog.id === analysisId ? fromCatalog.key : undefined;
}

/* ── supplier packages ──────────────────────────────────────────────────── */

export async function listPackages(): Promise<RfqPackageSummary[]> {
  const b = await json<{ packages: RfqPackageSummary[] }>(`/rfq-packages?limit=100`);
  return b.packages ?? [];
}

export async function getPackage(id: string): Promise<RfqPackageDetail> {
  const b = await json<{ package: RfqPackageDetail }>(`/rfq-packages/${encodeURIComponent(id)}`);
  return b.package;
}

export async function buildPackage(input: { ids: string[]; title: string; supplier: string; note: string; cad: boolean }): Promise<RfqPackageDetail> {
  const b = await json<{ package: RfqPackageDetail }>(
    `/rfq-packages`,
    body("POST", {
      decision_ids: input.ids,
      title: input.title.trim() || null,
      supplier_name: input.supplier.trim() || null,
      note: input.note.trim() || null,
      include_raw_cad: input.cad,
    }),
  );
  return b.package;
}

export async function downloadPackage(id: string, title: string | null): Promise<string> {
  const res = await send(`/rfq-packages/${encodeURIComponent(id)}/download.zip`);
  const name = `${stem((title || "supplier-package").replace(/[^A-Za-z0-9_. -]+/g, "_"))}.zip`;
  saveBlob(await res.blob(), name);
  return name;
}
