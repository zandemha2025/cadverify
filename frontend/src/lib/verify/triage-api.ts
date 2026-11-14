"use client";

/**
 * Triage-at-scale client for the Verify surface — the REAL org-scoped makeability
 * projection (backend/src/api/catalog.py, mounted at /api/v1/catalog). Every call
 * goes SAME-ORIGIN through the Next authed proxy (`/api/proxy/catalog/*`), so the
 * httpOnly session cookie authenticates it and no API key touches the browser.
 *
 * The four design buckets — makeable in-house / outside / needs new capability /
 * not makeable as drawn — are the IN-HOUSE MAKEABILITY breakdown
 * (GET /catalog/makeability): a SQL GROUP BY over the materialized part-summary
 * projection, whole inventory, never capped. The buckets sum to `total` (nothing
 * silently skipped), and every count opens into its verdicts via the ?bucket=
 * keyset drill-down. The capability-investment ranking (GET
 * /catalog/capability-investment) names the single (process, gate) acquisition
 * that unlocks the most currently-blocked parts, and ?process= opens the parts it
 * unlocks. NO acquisition dollar cost is ever fabricated (none is engine-derived).
 *
 * Honesty: every count is a projection of the Phase-C verification block the cost
 * path already computed — never re-invented. A verdict computed against inventory
 * that has since changed is carried as STALE (a visible count + flag), never served
 * as fresh. Empty org → a zeroed rollup; a cold projection says so plainly.
 */
import { API_BASE } from "../api-base.ts";

const BASE = `${API_BASE}/catalog`;

/** The six mutually-exclusive makeability buckets (they sum to `total`). */
export type MakeabilityBucketKey =
  | "makeable_in_house"
  | "makeable_outside"
  | "needs_capability"
  | "not_makeable"
  | "unknown"
  | "geometry_invalid";

export interface MakeabilitySummary {
  makeable_in_house: number;
  makeable_outside: number;
  needs_capability: number;
  not_makeable: number;
  unknown: number;
  geometry_invalid: number;
  total: number;
  stale: boolean;
  stale_count: number;
  truncated: boolean;
}

export interface MakeabilityRollup {
  summary: MakeabilitySummary;
  buckets: string[];
  /** True when the projection is cold (parts predate it / backfill not run). */
  cold_projection?: boolean;
  note?: string;
  stale_note?: string;
  evaluation_note?: string;
}

/** One part's makeability block, as the drill-down denormalizes it. */
export interface MakeabilityBlock {
  verdict: string | null;
  stale: boolean | null;
  gap: {
    kind?: string;
    process?: string | null;
    gate?: string | null;
    single?: boolean;
    gap?: unknown[];
  } | null;
}

/** One drill-down row: the derive_row dict + a makeability block (why). */
export interface MakeabilityRow {
  part_key: string;
  filename: string | null;
  file_type?: string | null;
  lifecycle_state?: string | null;
  recommended_route?: { process?: string | null } | null;
  unit_cost?: number | null;
  route_blocker_count?: number | null;
  updated_at?: string;
  makeability: MakeabilityBlock;
}

export interface BucketPage {
  rows: MakeabilityRow[];
  next_cursor: string | null;
}

/** Append a keyset page without rendering a part twice if pages overlap. */
export function mergeMakeabilityRows(
  current: MakeabilityRow[],
  incoming: MakeabilityRow[]
): MakeabilityRow[] {
  const seen = new Set(current.map((row) => row.part_key));
  const merged = [...current];
  for (const row of incoming) {
    if (seen.has(row.part_key)) continue;
    seen.add(row.part_key);
    merged.push(row);
  }
  return merged;
}

/** One acquisition in the capability-investment ranking. */
export interface CapabilityAcquisition {
  kind: "acquire" | "upgrade";
  process: string;
  process_label: string;
  gate: string | null;
  spec: { gate?: string; summary?: string; [k: string]: unknown };
}

export interface CapabilityEntry {
  acquisition: CapabilityAcquisition;
  parts_unlocked: number;
  stale: boolean;
  stale_parts: number;
  basis: string;
}

export interface CapabilityRanking {
  ranking: CapabilityEntry[];
  summary: {
    acquisitions: number;
    parts_unlockable_by_one_acquisition: number;
    blocked_by_multiple_constraints: number;
    total_blocked: number;
    stale: boolean;
    truncated: boolean;
  };
  basis_note?: string;
  stale_note?: string;
  note?: string;
}

export interface ManifestImportSummary {
  imported: number;
  updated: number;
  skipped: number;
  total: number;
  errors: { line: number; reason: string }[];
}

export interface RecurringBlockerAffectedPart {
  part_key: string;
  filename: string;
  analysis: { id: string; url: string };
  finding_ref: {
    scope: "universal" | "process";
    code: string;
    occurrence: number;
    process?: string;
  };
  message: string;
  fix_suggestion: string | null;
  created_at: string | null;
  analysis_version: string;
  stale: boolean;
  staleness: {
    analysis_version: "current" | "stale";
    part_summary: "current" | "missing" | "malformed" | "out_of_sync";
  };
}

export interface RecurringBlockerCluster {
  id: string;
  code: string;
  scope: "universal" | "process";
  process: string | null;
  severity: "error";
  message: string;
  fix_suggestion: string | null;
  affected_part_count: number;
  count_basis: "distinct_latest_parts";
  severity_basis: string;
  stale: boolean;
  stale_part_count: number;
  affected_parts: RecurringBlockerAffectedPart[];
  provenance: Record<string, string>;
}

export interface RecurringBlockerRollup {
  clusters: RecurringBlockerCluster[];
  summary: {
    latest_part_count: number;
    parts_with_blockers: number;
    recurring_cluster_count: number;
    recurring_affected_part_count: number;
    stale_affected_part_count: number;
    part_summary_count: number;
    malformed_analysis_count: number;
    malformed_part_summary_count: number;
    truncated: boolean;
  };
  provenance: {
    source: "ACTIVE_ORGANIZATION_LATEST_SAVED_ANALYSES";
    algorithm_version: string;
    minimum_distinct_parts: number;
    candidate_limit: number;
    scope: "WHOLE_ORGANIZATION" | "MOST_RECENT_LATEST_PARTS_BOUNDED";
    llm_inference: false;
  };
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function nullableString(value: unknown): boolean {
  return value === null || typeof value === "string";
}

function nonnegativeInteger(value: unknown): boolean {
  return Number.isInteger(value) && Number(value) >= 0;
}

function stringRecord(value: unknown): boolean {
  const row = objectValue(value);
  return !!row && Object.values(row).every((item) => typeof item === "string");
}

function isRecurringBlockerAffectedPart(
  value: unknown
): value is RecurringBlockerAffectedPart {
  const part = objectValue(value);
  const analysis = objectValue(part?.analysis);
  const finding = objectValue(part?.finding_ref);
  const staleness = objectValue(part?.staleness);
  return !!(
    part &&
    analysis &&
    finding &&
    staleness &&
    typeof part.part_key === "string" &&
    typeof part.filename === "string" &&
    typeof analysis.id === "string" &&
    typeof analysis.url === "string" &&
    new Set(["universal", "process"]).has(String(finding.scope)) &&
    typeof finding.code === "string" &&
    nonnegativeInteger(finding.occurrence) &&
    (finding.process === undefined || typeof finding.process === "string") &&
    typeof part.message === "string" &&
    nullableString(part.fix_suggestion) &&
    nullableString(part.created_at) &&
    typeof part.analysis_version === "string" &&
    typeof part.stale === "boolean" &&
    new Set(["current", "stale"]).has(String(staleness.analysis_version)) &&
    new Set(["current", "missing", "malformed", "out_of_sync"]).has(
      String(staleness.part_summary)
    )
  );
}

function isRecurringBlockerCluster(
  value: unknown
): value is RecurringBlockerCluster {
  const row = objectValue(value);
  const parts = row?.affected_parts;
  return !!(
    row &&
    typeof row.id === "string" &&
    typeof row.code === "string" &&
    new Set(["universal", "process"]).has(String(row.scope)) &&
    nullableString(row.process) &&
    row.severity === "error" &&
    typeof row.message === "string" &&
    nullableString(row.fix_suggestion) &&
    nonnegativeInteger(row.affected_part_count) &&
    row.count_basis === "distinct_latest_parts" &&
    typeof row.severity_basis === "string" &&
    typeof row.stale === "boolean" &&
    nonnegativeInteger(row.stale_part_count) &&
    Number(row.stale_part_count) <= Number(row.affected_part_count) &&
    Array.isArray(parts) &&
    row.affected_part_count === parts.length &&
    parts.every(isRecurringBlockerAffectedPart) &&
    stringRecord(row.provenance)
  );
}

export function isRecurringBlockerRollup(
  value: unknown
): value is RecurringBlockerRollup {
  const rollup = objectValue(value);
  const summary = objectValue(rollup?.summary);
  const provenance = objectValue(rollup?.provenance);
  const clusters = rollup?.clusters;
  const summaryCounts = [
    "latest_part_count",
    "parts_with_blockers",
    "recurring_cluster_count",
    "recurring_affected_part_count",
    "stale_affected_part_count",
    "part_summary_count",
    "malformed_analysis_count",
    "malformed_part_summary_count",
  ];
  return !!(
    rollup &&
    summary &&
    provenance &&
    Array.isArray(clusters) &&
    clusters.every(isRecurringBlockerCluster) &&
    summaryCounts.every((key) => nonnegativeInteger(summary[key])) &&
    typeof summary.truncated === "boolean" &&
    provenance.source === "ACTIVE_ORGANIZATION_LATEST_SAVED_ANALYSES" &&
    typeof provenance.algorithm_version === "string" &&
    nonnegativeInteger(provenance.minimum_distinct_parts) &&
    Number(provenance.minimum_distinct_parts) >= 2 &&
    nonnegativeInteger(provenance.candidate_limit) &&
    Number(provenance.candidate_limit) >= 1 &&
    new Set(["WHOLE_ORGANIZATION", "MOST_RECENT_LATEST_PARTS_BOUNDED"]).has(
      String(provenance.scope)
    ) &&
    provenance.llm_inference === false
  );
}

/** Relay the backend's structured error `detail` as the thrown Error message. */
async function toError(res: Response): Promise<Error> {
  const body = await res.json().catch(() => null);
  const detail =
    (body && (body.detail || body.message)) || `Request failed (${res.status})`;
  return new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
}

/** The whole-inventory in-house makeability rollup (the four design buckets). */
export async function fetchMakeability(): Promise<MakeabilityRollup> {
  const res = await fetch(`${BASE}/makeability`, { cache: "no-store" });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** One keyset page of the parts in a single bucket — "every count opens." */
export async function fetchMakeabilityBucket(
  bucket: MakeabilityBucketKey,
  cursor?: string | null
): Promise<BucketPage> {
  const u = new URL(`${BASE}/makeability`, window.location.origin);
  u.searchParams.set("bucket", bucket);
  if (cursor) u.searchParams.set("cursor", cursor);
  const res = await fetch(u.toString().replace(window.location.origin, ""), {
    cache: "no-store",
  });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** The capability-investment ranking: which ONE acquisition unlocks the most. */
export async function fetchCapabilityInvestment(): Promise<CapabilityRanking> {
  const res = await fetch(`${BASE}/capability-investment`, {
    cache: "no-store",
  });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** Exact recurring engine blockers across distinct latest saved parts. */
export async function fetchRecurringBlockers(): Promise<RecurringBlockerRollup> {
  const res = await fetch(
    `${API_BASE}/portfolio-intelligence/blocker-clusters`,
    { cache: "no-store" }
  );
  if (!res.ok) throw await toError(res);
  const value: unknown = await res.json();
  if (!isRecurringBlockerRollup(value)) {
    throw new Error("Unsafe recurring blocker response");
  }
  return value;
}

/** One keyset page of the parts a single acquisition unlocks (?process=&gate=). */
export async function fetchCapabilityUnlocked(
  process: string,
  gate: string | null,
  cursor?: string | null
): Promise<BucketPage> {
  const u = new URL(`${BASE}/capability-investment`, window.location.origin);
  u.searchParams.set("process", process);
  if (gate) u.searchParams.set("gate", gate);
  if (cursor) u.searchParams.set("cursor", cursor);
  const res = await fetch(u.toString().replace(window.location.origin, ""), {
    cache: "no-store",
  });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** Bulk manifest/BOM ingest: real POST /manifest/import with partial success. */
export async function importManifestCsv(file: File): Promise<ManifestImportSummary> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/manifest/import`, {
    method: "POST",
    body: form,
    cache: "no-store",
  });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** Human phrase for a makeability verdict (honest — never fabricated). */
export function verdictPhrase(verdict: string | null): string {
  switch (verdict) {
    case "makeable_in_house":
    case "makeable_with_secondary_op":
      return "fits an owned machine";
    case "makeable_outsource_only":
      return "no owned route — buyable outside";
    case "makeable_not_on_owned":
      return "owns the family, no machine fits";
    case "environment_excluded":
      return "excluded by the declared environment";
    case "not_makeable":
      return "fails physics on every route";
    default:
      return "evaluation requires a declared inventory";
  }
}
