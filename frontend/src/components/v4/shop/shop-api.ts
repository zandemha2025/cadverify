/**
 * Same-origin calls the Your shop screens need beyond the existing helpers in
 * lib/verify (machine-api, rate-api, calibration-api): shop operations, one
 * logged job, rate-card drafts sent for review, and the saved records the Rates
 * and Real costs pages read their numbers from.
 */
import { API_BASE } from "@/lib/api-base";

export class ShopApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ShopApiError";
    this.status = status;
    this.body = body;
  }
}

/** The server's own words when it has them (FastAPI `detail`, problem `message`), else the status. */
export function detailText(body: unknown, status: number): string {
  const b = body as { detail?: unknown; message?: unknown } | null;
  const d = b?.detail ?? b?.message;
  if (typeof d === "string" && d) return d;
  if (Array.isArray(d)) {
    const parts = d.map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg: unknown }).msg) : String(x)));
    return parts.join("; ");
  }
  if (d && typeof d === "object") {
    const o = d as { reason?: unknown; message?: unknown };
    if (typeof o.reason === "string") return o.reason;
    if (typeof o.message === "string") return o.message;
  }
  return `Request failed (${status})`;
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) throw new ShopApiError(detailText(body, res.status), res.status, body);
  return body as T;
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

/* ---------------- shop operations ---------------- */

export type ShopCapabilities = { ops: Record<string, unknown>; updated_at: string | null };

export function getShopCapabilities(): Promise<ShopCapabilities> {
  return call("/machine-inventory/shop-capabilities");
}

export function putShopCapabilities(ops: Record<string, unknown>): Promise<ShopCapabilities> {
  return call("/machine-inventory/shop-capabilities", json("PUT", { ops }));
}

/* ---------------- saved records ---------------- */

export type Assumption = { name: string; value: number; unit: string; provenance: string; source: string };

export type CostLine = { name: string; value: number; unit: string; provenance: string; source: string; error_band_pct?: number | null };

export type EstimateRow = {
  process: string;
  material: string;
  quantity: number;
  unit_cost_usd: number;
  drivers: CostLine[];
  confidence?: {
    low_usd?: number;
    high_usd?: number;
    point_usd?: number;
    half_width_pct?: number;
    method?: string;
    label?: string;
    validated?: boolean;
    n_samples?: number;
  } | null;
  machine_name?: string | null;
};

export type RecordSummary = {
  id: string;
  filename: string;
  label: string | null;
  mesh_hash?: string;
  make_now_process: string | null;
  created_at: string;
  quantities: number[];
  is_stale?: boolean;
};

export type RecordDetail = RecordSummary & {
  result: {
    assumptions?: Assumption[];
    estimates?: EstimateRow[];
    material_class?: string;
    decision?: {
      make_now_process?: string | null;
      make_now_material?: string | null;
      recommendation?: Record<string, { process: string; material: string; unit_cost_usd: number } | null>;
    } | null;
  } | null;
};

export async function listRecords(limit = 100): Promise<RecordSummary[]> {
  const out: RecordSummary[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < 5; page++) {
    const q: string = `?limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
    const body: { cost_decisions: RecordSummary[]; next_cursor: string | null; has_more?: boolean } = await call(`/cost-decisions${q}`);
    out.push(...(body.cost_decisions ?? []));
    cursor = body.has_more ? body.next_cursor : null;
    if (!cursor) break;
  }
  return out;
}

export function getRecord(id: string): Promise<RecordDetail> {
  return call(`/cost-decisions/${encodeURIComponent(id)}`);
}

/**
 * The newest saved record per part, newest first, in ONE request
 * (GET /cost-decisions/latest-per-part): a summary for every part, and for the
 * newest `detailLimit` parts the fields Rates and Real costs read (assumptions,
 * material class, the decision's pick, the estimates at `headline_qty`). One
 * call per screen load instead of a per-record read for each part.
 */
export type PartRecords = {
  parts: RecordSummary[];
  total_parts: number;
  has_more: boolean;
  details: (RecordDetail & { headline_qty: number | null })[];
};

export function getLatestPerPart(detailLimit = 12): Promise<PartRecords> {
  return call(`/cost-decisions/latest-per-part?detail_limit=${detailLimit}`);
}

/** The newest record per part (by mesh hash, else filename), newest first. */
export function latestPerPart(records: RecordSummary[]): RecordSummary[] {
  const seen = new Set<string>();
  const out: RecordSummary[] = [];
  for (const r of [...records].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))) {
    const key = r.mesh_hash || r.filename;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(r);
  }
  return out;
}

/* ---------------- rate card drafts and review ---------------- */

export type RateVersionFull = {
  id: number;
  version: number;
  name: string;
  status: string;
  change_note: string;
  effective_from: string | null;
  created_at: string | null;
  published_at: string | null;
  payload?: Record<string, unknown> | null;
};

export function getRateVersion(id: number): Promise<RateVersionFull> {
  return call(`/rate-library/${id}`);
}

export function createRateDraft(body: { name: string; change_note: string; from_version_id?: number | null }): Promise<RateVersionFull> {
  return call("/rate-library", json("POST", body));
}

export function updateRateDraft(id: number, body: { payload: Record<string, unknown> }): Promise<RateVersionFull> {
  return call(`/rate-library/${id}`, json("PATCH", body));
}

export function discardRateDraft(id: number): Promise<unknown> {
  return call(`/rate-library/${id}`, { method: "DELETE" });
}

export type ChangeRequestRow = {
  id: number;
  asset_type: string;
  target_version_id: number;
  status: string;
  title: string;
  note: string;
  proposed_by: number | null;
  reviewed_by: number | null;
  created_at: string | null;
  decided_at: string | null;
  [k: string]: unknown;
};

export function proposeChange(body: { asset_type: string; target_version_id: number; title: string; note: string }): Promise<ChangeRequestRow> {
  return call("/governance/change-requests", json("POST", body));
}

export function listChanges(): Promise<{ change_requests: ChangeRequestRow[] }> {
  return call("/governance/change-requests");
}

export function approveChange(id: number): Promise<{ change_request: ChangeRequestRow; published_version: RateVersionFull | null }> {
  return call(`/governance/change-requests/${id}/approve`, json("POST", {}));
}

export function rejectChange(id: number, note: string): Promise<ChangeRequestRow> {
  return call(`/governance/change-requests/${id}/reject`, json("POST", { note }));
}

/* ---------------- real costs ---------------- */

export type GroundTruthIn = {
  part_id: string;
  process: string;
  quantity: number;
  actual_unit_cost_usd: number;
  material_class: string;
  source: string;
  source_type: string;
  invoice_date?: string | null;
  actual_machine_hours?: number | null;
  actual_setup_hours?: number | null;
  actual_labor_hours?: number | null;
  actual_inspection_hours?: number | null;
};

export function logJob(body: GroundTruthIn): Promise<{ id: string }> {
  return call("/ground-truth", json("POST", body));
}

/** A blob download of text the server produced (a CSV template). */
export function downloadText(text: string, filename: string): void {
  const href = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}
