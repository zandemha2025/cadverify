/**
 * The shapes the Home, Parts and Setup screens read from the API, kept
 * structural and import-free so the derivations unit-test under `node --test`.
 * Each mirrors a real endpoint response (field names verbatim).
 */

/** GET /catalog row (catalog_service.derive_row), the fields these screens read. */
export interface PartRow {
  part_key: string;
  filename: string;
  file_type: string;
  lifecycle_state: "Drafted" | "Costed";
  recommended_route: { process: string; material: string | null; source: "costed" | "dfm" } | null;
  unit_cost: {
    usd: number | null;
    qty: number | null;
    withheld: boolean;
    withheld_reason: string | null;
    validated: boolean;
  } | null;
  findings: { total: number; critical: number; advisory: number; info: number; scoped_process: string } | null;
  provenance_posture: { measured: number; shop: number; user: number; default: number; total: number } | null;
  route_blocker_count: number;
  cost_decision: { id: string } | null;
  analysis: { id: string } | null;
  updated_at: string;
}

/** The six makeability buckets GET /catalog/makeability partitions an org's parts into. */
export type Bucket =
  | "makeable_in_house"
  | "makeable_outside"
  | "needs_capability"
  | "not_makeable"
  | "unknown"
  | "geometry_invalid";

export const BUCKETS: Bucket[] = [
  "makeable_in_house",
  "makeable_outside",
  "needs_capability",
  "not_makeable",
  "unknown",
  "geometry_invalid",
];

/** GET /catalog/makeability rollup summary. */
export interface MakeSummary {
  makeable_in_house: number;
  makeable_outside: number;
  needs_capability: number;
  not_makeable: number;
  unknown: number;
  geometry_invalid: number;
  total: number;
  stale_count: number;
  stale: boolean;
  truncated: boolean;
}

export interface FitGap {
  gate: string;
  axis: string;
  need: unknown;
  have: unknown;
  human: string;
}

/** The `makeability` block on a GET /catalog/makeability?bucket= drill-down row. */
export interface Makeability {
  verdict: string;
  stale: boolean;
  gap: { gap?: FitGap[]; gate?: string; kind?: string; process?: string } | null;
}

export interface MakeRow extends PartRow {
  makeability: Makeability;
}

/** GET /cost-decisions summary row, the fields these screens read. */
export interface RecordRow {
  id: string;
  mesh_hash?: string;
  filename: string;
  label: string | null;
  make_now_process: string | null;
  created_at: string;
  approval_status?: string | null;
  is_stale?: boolean;
  user_disposition?: string | null;
  user_disposition_label?: string | null;
}

export interface MachineRow {
  name: string;
  process: string;
  count: number;
  hourly_rate_usd: number | null;
}

export interface ChangeRow {
  id: number | string;
  status: string;
  asset_type: string;
  title: string;
}

/** GET /catalog/portfolio summary.posture (driver provenance across costed parts). */
export interface Posture {
  measured: number;
  shop: number;
  user: number;
  default: number;
  total: number;
}

/** GET /rate-library/effective. */
export interface RateSource {
  using_governed: boolean;
  source: string;
  provenance: string;
}
