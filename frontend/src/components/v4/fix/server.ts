"use client";

/**
 * Fixes ScaleCAD applies itself to an uploaded part's kept source CAD
 * (backend api/part_fixes.py, services/cad_fix_service.py):
 *  - GET  /parts/{hash}/fixes            per finding: can ScaleCAD fix it, with which fix and parameter;
 *  - POST /parts/{hash}/fixes/{fix_id}   the fix on a copy, re-checked and priced in the same request;
 *  - GET  /parts/{hash}/fixed-file       the fixed copy (only copies ScaleCAD made).
 * On every plan like mesh repair; the copy is saved as a new part linked to the
 * original, and no part check is used (the response says so: checks_used). A
 * free account over its hourly or daily ceiling gets the server's message (429).
 */
import * as React from "react";
import { API_BASE } from "@/lib/api-base";
import { apiProblemDetail, apiRecoveryMessage } from "@/lib/api-recovery";
import type { ServerFixes } from "./capabilities";

export interface ServerFinding {
  code: string;
  family: string | null;
  severity: string | null;
  processes: string[];
  required: Record<string, number>;
  unit: string | null;
  fix: string | null;
  why_not: string | null;
  can_fix: boolean;
  params: Record<string, number> | null;
  attempt: { outcome?: string; summary?: string; fixed_mesh_hash?: string } | null;
}

export interface ServerFixSpec {
  id: string;
  label: string;
  method: string;
  available: boolean;
  why_not: string | null;
  codes: string[];
  param: string | null;
  unit: string | null;
  bounds: [number, number] | null;
  params: Record<string, number>;
  applies_to_this_part: boolean;
}

export interface ServerOptions {
  format: string;
  findings: ServerFinding[];
  fixes: ServerFixSpec[];
  families: string[];
  can_fix_count: number;
  finding_count: number;
  derived_from: { parent_mesh_hash: string; parent_filename: string; fix: string; params: Record<string, number> } | null;
}

export interface FixSide {
  mesh_hash: string;
  sha256: string;
  format: string;
  bytes: number;
  verdict: string | null;
  faces: number | null;
  volume_mm3: number | null;
  is_watertight: boolean | null;
  methods_can_make: { count: number; of: number; processes: string[] };
  decimated_for_analysis: boolean;
  filename?: string;
}

export interface FindingBrief {
  code: string;
  process: string | null;
  severity: string | null;
  message: string | null;
  measured_value?: number;
  required_value?: number;
  measurement_unit?: string;
  targeted?: boolean;
  meets_rule?: boolean | null;
}

export interface PriceRow {
  qty: number;
  process: string | null;
  material: string | null;
  unit_cost_usd: number | null;
}

export interface ServerFixResult {
  fix: { id: string; label: string; method: string; params: Record<string, number> };
  original: FixSide;
  applied: boolean;
  outcome: "cleared" | "partly_cleared" | "not_cleared" | "nothing_to_clear" | "not_applied";
  reason: string | null;
  details: { duration_ms?: number; [k: string]: unknown };
  fixed: FixSide | null;
  targeted: { codes: string[]; before: FindingBrief[]; cleared: FindingBrief[]; remaining: FindingBrief[] } | null;
  findings_cleared: FindingBrief[];
  findings_new: FindingBrief[];
  new_error_count: number;
  volume_change_pct: number | null;
  volume_warning: string | null;
  prices: { quantities: number[]; material_class: string; basis: string; before: PriceRow[] | null; after: PriceRow[] | null; note: string } | null;
  notes: string[];
  verification: { reverified: boolean; comparable: boolean; original_verdict: string | null; fixed_verdict: string | null; original_sha256: string; fixed_sha256: string; checks_used: number } | null;
  download: { url: string; filename: string; media_type: string; bytes: number } | null;
}

/** What one fix request came back with. */
export type ServerFixOutcome = { s: "error"; msg: string } | { s: "done"; r: ServerFixResult };

const cache = new Map<string, Promise<ServerOptions | null>>();

/** GET /parts/{hash}/fixes; null when the part has no kept source (or the server has no answer). */
export function loadServerOptions(key: string, fresh = false): Promise<ServerOptions | null> {
  if (fresh || !cache.has(key)) {
    cache.set(
      key,
      fetch(`${API_BASE}/parts/${encodeURIComponent(key)}/fixes`, { cache: "no-store" })
        .then(async (r) => (r.ok ? ((await r.json()) as ServerOptions) : null))
        .catch(() => null),
    );
  }
  return cache.get(key)!;
}

export function useServerOptions(key: string | null, tick = 0): ServerOptions | null {
  const [state, setState] = React.useState<{ key: string; tick: number; o: ServerOptions | null } | null>(null);
  React.useEffect(() => {
    if (!key) return;
    let live = true;
    void loadServerOptions(key, tick > 0).then((o) => {
      if (live) setState({ key, tick, o });
    });
    return () => {
      live = false;
    };
  }, [key, tick]);
  return state && state.key === key ? state.o : null;
}

/** The seam capabilities.ts reads: which problem families ScaleCAD can fix on this file, and how. */
export function serverFixesOf(o: ServerOptions | null): ServerFixes | null {
  if (!o) return null;
  const byFamily: ServerFixes["byFamily"] = {};
  for (const f of o.findings) {
    if (!f.family || !f.fix) continue;
    const spec = o.fixes.find((x) => x.id === f.fix) ?? null;
    const prev = byFamily[f.family];
    if (prev?.can && !f.can_fix) continue;
    byFamily[f.family] = {
      can: f.can_fix,
      fix: f.fix,
      label: spec?.label ?? f.fix,
      method: spec?.method ?? "",
      param: spec?.param ?? null,
      unit: spec?.unit ?? null,
      bounds: spec?.bounds ?? null,
      value: f.params && spec?.param ? f.params[spec.param] ?? null : null,
      whyNot: f.why_not,
      lastAttempt: f.attempt?.summary ?? null,
    };
  }
  for (const f of o.findings) {
    if (f.family && !f.fix && f.why_not && !byFamily[f.family]) byFamily[f.family] = { can: false, fix: null, label: "", method: "", param: null, unit: null, bounds: null, value: null, whyNot: f.why_not, lastAttempt: null };
  }
  return { families: o.families, byFamily, available: o.fixes.filter((x) => x.available || x.why_not?.startsWith("Not for")).map((x) => ({ id: x.id, label: x.label })) };
}

/** POST /parts/{hash}/fixes/{fixId}: the fix on a copy, re-checked and priced. */
export async function applyServerFix(key: string, fixId: string, opts: { value?: number | null; qty?: number[]; materialClass?: string | null }): Promise<ServerFixOutcome> {
  const q = new URLSearchParams();
  if (opts.value != null && Number.isFinite(opts.value)) q.set("value", String(opts.value));
  if (opts.qty?.length) q.set("qty", opts.qty.join(","));
  if (opts.materialClass) q.set("material_class", opts.materialClass);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/parts/${encodeURIComponent(key)}/fixes/${encodeURIComponent(fixId)}${q.toString() ? `?${q}` : ""}`, { method: "POST" });
  } catch {
    return { s: "error", msg: "The fix couldn't reach the server. Try again." };
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    return { s: "error", msg: apiProblemDetail(body) ?? apiRecoveryMessage({ status: res.status, payload: body, resource: "fix" }) };
  }
  cache.delete(key);
  return { s: "done", r: body as ServerFixResult };
}

/** The fixed copy's download, through the same-origin proxy. */
export function fixedFileUrl(fixedHash: string): string {
  return `${API_BASE}/parts/${encodeURIComponent(fixedHash)}/fixed-file`;
}
