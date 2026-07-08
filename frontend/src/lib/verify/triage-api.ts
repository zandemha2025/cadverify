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
import { API_BASE } from "@/lib/api-base";

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
