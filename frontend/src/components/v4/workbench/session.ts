"use client";

/**
 * The Workbench session: one part at a time, held in memory for this browser
 * tab so switching Workbench tabs, or leaving and coming back, keeps the file,
 * the results, overrides and scenarios. Nothing here is written to disk; a
 * reload starts from the part's saved records (`?part=<mesh hash>`), which
 * carry the cost decision and DFM analysis but not the CAD bytes, so anything
 * that re-costs asks for the same file again.
 *
 * Every number comes from the API: POST /validate/cost (each re-cost is a real
 * engine run), POST /validate, and the saved cost-decision and analysis records.
 */
import * as React from "react";
import {
  CostGeometryInvalidError,
  costEstimate,
  fetchAnalysis,
  fetchCatalog,
  fetchCostDecision,
  fetchCostDecisions,
  fetchRfqPackage,
  fetchRfqPackages,
  getShops,
  validateFile,
  type CostDecisionSummary,
  type CostGeometry,
  type CostOptions,
  type CostReport,
  type ShopProfileInfo,
  type ValidationResult,
} from "@/lib/api";
import { partCheckHeaders } from "@/lib/verify/check-id";
import { computeMeshHash } from "@/lib/verify/part-context";
import { fetchPartContext } from "@/lib/verify/part-context-read";
import { environmentLabel } from "./words";
import { optionsFromReport } from "./derive";

export type Phase = "idle" | "running" | "done" | "error";

export interface Scenario {
  id: string;
  label: string;
  unit: number | null;
  qty: number | null;
  process: string | null;
  opts: CostOptions;
}

export interface RunSlot {
  phase: Phase;
  report: CostReport | null;
  error: string | null;
}

export interface WbState {
  /** SHA-256 of the CAD bytes (the part key the records use). */
  key: string | null;
  filename: string | null;
  file: File | null;
  /** "session": costed in this tab; "saved": opened from the part's records. */
  source: "none" | "session" | "saved";
  load: { phase: Phase; error: string | null };
  decisions: CostDecisionSummary[] | null;
  decisionsError: string | null;
  decision: { id: string; created_at: string | null; approval_status?: string | null; is_public: boolean; share_url: string | null } | null;
  /** The inputs behind `report` (never the editable draft). */
  opts: CostOptions;
  report: CostReport | null;
  /** The last report with no overrides, for "vs no overrides". */
  baseline: CostReport | null;
  cost: { phase: Phase; error: string | null; geom: { reason: string | null; geometry: CostGeometry | null } | null; pending: CostOptions | null };
  validation: ValidationResult | null;
  dfm: { phase: Phase; error: string | null };
  env: string | null;
  scenarios: Scenario[];
  /** Compare by rates: one engine run per rate set, keyed "base" or a shop id. */
  runs: Record<string, RunSlot>;
  runsSig: string | null;
  pkgId: string | null;
}

export const DEFAULT_OPTIONS: CostOptions = {
  qty: "50,5000",
  region: "auto",
  cavities: 1,
  complexity: "moderate",
  material_class: "polymer",
  units: "mm",
  shop: null,
  overrides: {},
};

function empty(): WbState {
  return {
    key: null,
    filename: null,
    file: null,
    source: "none",
    load: { phase: "idle", error: null },
    decisions: null,
    decisionsError: null,
    decision: null,
    opts: DEFAULT_OPTIONS,
    report: null,
    baseline: null,
    cost: { phase: "idle", error: null, geom: null, pending: null },
    validation: null,
    dfm: { phase: "idle", error: null },
    env: null,
    scenarios: [],
    runs: {},
    runsSig: null,
    pkgId: null,
  };
}

let state: WbState = empty();
let gen = 0;
let costSeq = 0;
let dfmSeq = 0;
let lastRunFile: File | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

function set(patch: Partial<WbState> | ((s: WbState) => Partial<WbState>)) {
  const p = typeof patch === "function" ? patch(state) : patch;
  state = { ...state, ...p };
  emit();
}

export function getWb(): WbState {
  return state;
}

export function useWb(): WbState {
  return React.useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
    () => state,
  );
}

function message(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/* ---- shared reads ------------------------------------------------ */

let shopsP: Promise<ShopProfileInfo[]> | null = null;
export function loadShops(): Promise<ShopProfileInfo[]> {
  if (!shopsP) {
    shopsP = getShops()
      .then((r) => r.shops ?? [])
      .catch((e) => {
        shopsP = null;
        throw e;
      });
  }
  return shopsP;
}

export function useShops(): { shops: ShopProfileInfo[]; error: string | null } {
  const [v, setV] = React.useState<{ shops: ShopProfileInfo[]; error: string | null }>({ shops: [], error: null });
  React.useEffect(() => {
    let live = true;
    loadShops().then(
      (shops) => live && setV({ shops, error: null }),
      (e) => live && setV({ shops: [], error: message(e, "Shops didn’t load.") }),
    );
    return () => {
      live = false;
    };
  }, []);
  return v;
}

async function refreshDecisions(key: string, g: number) {
  try {
    const page = await fetchCostDecisions({ meshHash: key, limit: 50 });
    if (g !== gen) return;
    set({ decisions: page.cost_decisions ?? [], decisionsError: null });
  } catch (e) {
    if (g !== gen) return;
    set({ decisionsError: message(e, "Saved decisions didn’t load.") });
  }
}

async function loadEnv(key: string, g: number) {
  const r = await fetchPartContext(key).catch(() => null);
  if (g !== gen || !r?.context) return;
  set({ env: environmentLabel(r.context.service_environment ?? null) });
}

/* ---- costing ----------------------------------------------------- */

function fresh(file: File): File {
  // A re-cost is a new run: a fresh File gets a fresh x-part-check-id. The
  // server counts it under the same file's check, so it never uses another.
  return new File([file], file.name, { type: file.type, lastModified: file.lastModified });
}

async function runCost(runFile: File, opts: CostOptions, g: number): Promise<CostReport | null> {
  const seq = ++costSeq;
  set((s) => ({ cost: { ...s.cost, phase: "running", error: null, geom: null, pending: opts } }));
  try {
    const report = await costEstimate(runFile, opts, partCheckHeaders(runFile)["x-part-check-id"]);
    if (g !== gen || seq !== costSeq) return null;
    const noOverrides = !opts.overrides || Object.keys(opts.overrides).length === 0;
    set((s) => ({
      report,
      opts,
      baseline: noOverrides ? report : s.baseline,
      cost: { phase: "done", error: null, geom: null, pending: null },
      decision: report.saved ? { id: report.saved.id, created_at: new Date().toISOString(), approval_status: "unreviewed", is_public: false, share_url: null } : s.decision,
      pkgId: report.saved && report.saved.id !== s.decision?.id ? null : s.pkgId,
    }));
    if (state.key) void refreshDecisions(state.key, g);
    return report;
  } catch (e) {
    if (g !== gen || seq !== costSeq) return null;
    if (e instanceof CostGeometryInvalidError) {
      set((s) => ({ cost: { ...s.cost, phase: "error", error: e.message, geom: { reason: e.message, geometry: e.geometry } } }));
    } else {
      set((s) => ({ cost: { ...s.cost, phase: "error", error: message(e, "The cost didn’t finish."), geom: null } }));
    }
    return null;
  } finally {
    window.dispatchEvent(new Event("proofshape:usage-changed"));
  }
}

async function runDfm(runFile: File, units: CostOptions["units"], g: number) {
  const seq = ++dfmSeq;
  set({ dfm: { phase: "running", error: null } });
  try {
    const v = await validateFile(runFile, undefined, undefined, undefined, units, partCheckHeaders(runFile)["x-part-check-id"]);
    if (g !== gen || seq !== dfmSeq) return;
    set({ validation: v, dfm: { phase: "done", error: null } });
  } catch (e) {
    if (g !== gen || seq !== dfmSeq) return;
    set({ dfm: { phase: "error", error: message(e, "The DFM check didn’t finish.") } });
  } finally {
    window.dispatchEvent(new Event("proofshape:usage-changed"));
  }
}

/** Start a new part from a dropped file: hash it, then cost and check it in parallel. */
export async function beginPart(file: File, opts: CostOptions): Promise<string | null> {
  const g = ++gen;
  const key = await computeMeshHash(file).catch(() => null);
  if (g !== gen) return null;
  state = { ...empty(), key, filename: file.name, file, source: "session", opts };
  lastRunFile = file;
  emit();
  if (key) {
    void loadEnv(key, g);
  }
  void runDfm(file, opts.units, g);
  await runCost(file, opts, g);
  return key;
}

/** Try the same file and options again after a failed first cost (F9 "Try again"). */
export async function retryBegin(): Promise<void> {
  const s = state;
  if (!s.file) return;
  const g = gen;
  const runFile = fresh(s.file);
  lastRunFile = runFile;
  if (s.dfm.phase === "error" || !s.validation) void runDfm(runFile, s.opts.units, g);
  await runCost(runFile, s.cost.pending ?? s.opts, g);
}

/** Re-cost with new inputs (a real engine run). Needs the file in this tab. */
export async function recost(opts: CostOptions): Promise<CostReport | null> {
  const s = state;
  if (!s.file) return null;
  const g = gen;
  const runFile = fresh(s.file);
  lastRunFile = runFile;
  if (opts.units !== s.opts.units) void runDfm(runFile, opts.units, g);
  return runCost(runFile, opts, g);
}

export function retryCost(): Promise<CostReport | null> {
  return recost(state.cost.pending ?? state.opts);
}

/** Re-run the DFM check only; the cost stays. */
export function retryDfm(): void {
  const f = lastRunFile ?? state.file;
  if (!f) return;
  void runDfm(fresh(f), state.opts.units, gen);
}

/* ---- saved records ----------------------------------------------- */

/**
 * Open a part from its records: the chosen (or latest) saved cost decision and
 * the part's saved DFM analysis. Keeps an in-tab session for the same part.
 */
export async function loadSaved(key: string, decisionId: string | null): Promise<void> {
  const s = state;
  if (s.key === key) {
    const same = !decisionId || s.decision?.id === decisionId;
    if (s.source === "session" && same) return;
    if (s.source === "saved" && same && s.load.phase !== "error") return;
    // Otherwise a different saved decision of this part: open it, keep the file.
  }
  const keepFile = s.key === key ? s.file : null;
  const keepScen = s.key === key ? s.scenarios : [];
  const g = ++gen;
  state = { ...empty(), key, file: keepFile, filename: keepFile?.name ?? null, source: "saved", scenarios: keepScen, load: { phase: "running", error: null } };
  emit();
  void loadEnv(key, g);
  try {
    const [page, catalog] = await Promise.all([
      fetchCostDecisions({ meshHash: key, limit: 50 }),
      fetchCatalog({ partKey: key, pageSize: 5 }).catch(() => null),
    ]);
    if (g !== gen) return;
    const list = page.cost_decisions ?? [];
    const row = catalog?.rows?.find((r) => r.part_key === key) ?? null;
    set({ decisions: list, filename: state.filename ?? list[0]?.filename ?? row?.filename ?? null });
    const pick = (decisionId && list.find((d) => d.id === decisionId)) || list[0] || null;
    const analysisId = row?.analysis?.id ?? null;
    const shops = await loadShops().catch(() => [] as ShopProfileInfo[]);
    const [detail, analysis] = await Promise.all([
      pick ? fetchCostDecision(pick.id) : Promise.resolve(null),
      analysisId ? fetchAnalysis(analysisId).catch(() => null) : Promise.resolve(null),
    ]);
    if (g !== gen) return;
    if (!detail && !analysis && !row) {
      set({ load: { phase: "error", error: "No saved part has this key in your organization." } });
      return;
    }
    const report = detail?.result ?? null;
    const validation = (analysis?.result_json ?? (analysis as unknown as { result?: ValidationResult } | null)?.result) ?? null;
    const units = validation?.source_units?.declared === "inch" ? "inch" : "mm";
    set({
      report,
      baseline: report,
      opts: report ? optionsFromReport(report, shops, units) : state.opts,
      decision: detail ? { id: detail.id, created_at: detail.created_at, approval_status: detail.approval_status ?? null, is_public: detail.is_public, share_url: detail.share_url } : null,
      validation,
      dfm: { phase: validation ? "done" : analysisId ? "error" : "idle", error: validation ? null : analysisId ? "The saved DFM analysis didn’t load." : null },
      cost: { phase: report ? "done" : "idle", error: null, geom: null, pending: null },
      filename: state.filename ?? detail?.filename ?? analysis?.filename ?? row?.filename ?? null,
      load: { phase: "done", error: null },
    });
  } catch (e) {
    if (g !== gen) return;
    set({ load: { phase: "error", error: message(e, "This part’s records didn’t load.") } });
  }
}

/** Re-attach the CAD file to a part opened from its records. */
export async function attachFile(file: File): Promise<"ok" | "different" | "unreadable"> {
  const key = await computeMeshHash(file).catch(() => null);
  if (!key) return "unreadable";
  if (key !== state.key) return "different";
  lastRunFile = file;
  set({ file, filename: state.filename ?? file.name });
  return "ok";
}

export function resetSession(): void {
  gen++;
  lastRunFile = null;
  state = empty();
  emit();
}

/* ---- scenarios, rate sets, packages ------------------------------ */

export function addScenario(s: Omit<Scenario, "id">): void {
  set((st) => ({ scenarios: [...st.scenarios, { ...s, id: `${Date.now()}-${st.scenarios.length}` }] }));
}

function runsSignature(opts: CostOptions): string {
  return JSON.stringify([opts.qty, opts.region, opts.cavities, opts.complexity, opts.material_class, opts.units, opts.overrides ?? {}]);
}

/** Compare by rates: price the part once per rate set (typical, then each shop). */
export async function runRateSets(shops: readonly ShopProfileInfo[]): Promise<void> {
  const s = state;
  if (!s.file) return;
  const g = gen;
  const sig = runsSignature(s.opts);
  const ids = ["base", ...shops.map((x) => x.id)];
  const runs: Record<string, RunSlot> = sig === s.runsSig ? { ...s.runs } : {};
  // The current report already is one of the rate sets.
  const curId = s.opts.shop ?? "base";
  if (s.report && !runs[curId]) runs[curId] = { phase: "done", report: s.report, error: null };
  for (const id of ids) if (!runs[id] || runs[id].phase === "error") runs[id] = { phase: "running", report: null, error: null };
  set({ runs, runsSig: sig });
  // One at a time: the API refuses too many concurrent checks for one account.
  for (const id of ids) {
    if (state.runs[id]?.phase !== "running") continue;
    if (g !== gen || state.runsSig !== sig) return;
    const f = fresh(s.file);
    try {
      const r = await costEstimate(f, { ...s.opts, shop: id === "base" ? null : id }, partCheckHeaders(f)["x-part-check-id"]);
      if (g !== gen || state.runsSig !== sig) return;
      set((st) => ({ runs: { ...st.runs, [id]: { phase: "done", report: r, error: null } } }));
    } catch (e) {
      if (g !== gen || state.runsSig !== sig) return;
      set((st) => ({ runs: { ...st.runs, [id]: { phase: "error", report: null, error: message(e, "That run didn’t finish.") } } }));
    } finally {
      window.dispatchEvent(new Event("proofshape:usage-changed"));
    }
  }
}

export function currentRunsSig(): string {
  return runsSignature(state.opts);
}

export function setPackage(id: string | null): void {
  set({ pkgId: id });
}

/** Find a supplier package already built for exactly this one decision. */
export async function findPackage(decisionId: string): Promise<string | null> {
  const page = await fetchRfqPackages(50);
  const singles = (page.packages ?? []).filter((p) => p.item_count === 1).slice(0, 20);
  const details = await Promise.all(singles.map((p) => fetchRfqPackage(p.id).catch(() => null)));
  const hit = details.find((d) => d?.items?.some((i) => i.decision?.id === decisionId));
  return hit?.id ?? null;
}

export function markShared(url: string): void {
  set((s) => ({ decision: s.decision ? { ...s.decision, is_public: true, share_url: url } : s.decision }));
}

/** Re-read this part's saved decisions (History's Retry). */
export function reloadDecisions(): void {
  if (state.key) void refreshDecisions(state.key, gen);
}
