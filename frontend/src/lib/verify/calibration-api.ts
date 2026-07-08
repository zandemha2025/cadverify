/**
 * Calibration & truth clients — the REAL governed-truth surface behind the
 * product "Calibration & truth" screen. Every call goes SAME-ORIGIN through the
 * Next authed proxy (`/api/proxy/*` → backend `/api/v1/*`), so the httpOnly
 * `dash_session` cookie authenticates it and no API key ever touches the browser.
 *
 * Backends wired here (all real):
 *   - rate-library      GET (versions) + GET /effective + GET /{id} + publish
 *   - governance        GET /change-requests + approve/reject
 *   - ground-truth      GET (records) + POST /recalibrate + POST /import
 *   - admin             GET /users + PATCH /users/{id}/role + GET /audit-log
 *                       + usage summary + webhook delivery log
 *   - keys              GET /api/v1/keys
 *
 * Honesty: NO design fixtures. The design's "Midwest Precision CNC · 19 rates",
 * "$52 → $54", and fake usage counters are ILLUSTRATIVE mockup data and are
 * NOT reproduced. Usage and webhook rows are read from the durable backend
 * tables. A governed rate card is DEFAULT assumptions
 * (`validated:false`), never ● SHOP. A calibration band flips SOLID only when the
 * recalibrate endpoint returns `validated:true` from REAL held-out residuals;
 * below the floor it is REFUSED (422) and the band stays hatched.
 */
import { API_BASE } from "@/lib/api-base";
// Reuse the frozen rate-library read client (do not re-implement its reads).
export {
  listRateVersions,
  effectiveRateCard,
  type RateCardVersion,
  type RateVersionsPage,
  type EffectiveRateCard,
} from "./rate-api";

/** An HTTP error that preserves the status so callers can tell 403 (permission-
 *  gated → honest gated state) apart from a real failure. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function toError(res: Response): Promise<ApiError> {
  const body = await res.json().catch(() => null);
  const detail =
    (body && ((body as { detail?: unknown }).detail ?? (body as { message?: unknown }).message)) ||
    `Request failed (${res.status})`;
  const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
  return new ApiError(msg, res.status, body);
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw await toError(res);
  return res.json() as Promise<T>;
}

async function sendJson<T>(
  path: string,
  method: "POST" | "PATCH",
  body?: unknown
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw await toError(res);
  return res.json() as Promise<T>;
}

// ── rate-library (the governed rate card the engine actually costs against) ──

/** Full rate-card version incl. its payload (rate table). */
export async function getRateCard(id: number): Promise<
  import("./rate-api").RateCardVersion & { payload?: Record<string, unknown> | null }
> {
  return getJson(`/rate-library/${id}`);
}

// ── governance (rates are versioned, not edited: change-request → review) ──

export interface ChangeRequest {
  id: number;
  ulid?: string;
  org_id?: string;
  asset_type: string;
  target_version_id: number;
  status: string; // proposed | approved | rejected
  title: string;
  note: string;
  proposed_by: number | null;
  reviewed_by: number | null;
  created_at: string | null;
  decided_at: string | null;
}

export async function listChangeRequests(
  status?: string
): Promise<{ change_requests: ChangeRequest[] }> {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return getJson(`/governance/change-requests${q}`);
}

export async function approveChangeRequest(id: number): Promise<{
  change_request: ChangeRequest;
  published_version: unknown;
}> {
  return sendJson(`/governance/change-requests/${id}/approve`, "POST", {});
}

export async function rejectChangeRequest(
  id: number,
  note = ""
): Promise<ChangeRequest> {
  return sendJson(`/governance/change-requests/${id}/reject`, "POST", { note });
}

// ── ground-truth (The Hallmark flywheel) ──

export interface GroundTruthRecord {
  id: string;
  part_id: string;
  process: string;
  quantity: number;
  actual_unit_cost_usd: number;
  material_class: string;
  shop: string | null;
  region: string | null;
  currency: string;
  source: string;
  /** True = synthetic stand-in — CAN shape a spread but NEVER flips validated. */
  stand_in: boolean;
  part_path: string | null;
  notes: string;
  created_at: string | null;
}

export interface GroundTruthList {
  records: GroundTruthRecord[];
  total: number;
}

/** The recalibrate summary. `validated` is true ONLY from REAL held-out
 *  residuals — the single signal that earns a SOLID band. */
export interface RecalibrateResult {
  org_id: string;
  n_records: number;
  n_real: number;
  n_standin: number;
  n_skipped: number;
  from_real: boolean;
  validated: boolean;
  claim: string | null;
  heldout_metrics_real: Record<string, unknown> | null;
  saved_path?: string;
}

/** The 422 body the backend returns below the real-record floor. */
export interface InsufficientGroundTruth {
  reason: string;
  n_real: number;
  n_records: number;
  min_real: number;
}

export async function listGroundTruth(): Promise<GroundTruthList> {
  return getJson(`/ground-truth`);
}

/** Trigger recalibration. Throws `ApiError` (status 422) below the floor with a
 *  structured `InsufficientGroundTruth` body — the band must stay hatched. */
export async function recalibrate(): Promise<RecalibrateResult> {
  return sendJson(`/ground-truth/recalibrate`, "POST", {});
}

export interface GroundTruthImportSummary {
  imported: number;
  skipped: number;
  total: number;
  errors: { line: number; reason: string }[];
}

/** Send reality back: import a historical-cost CSV. Imported rows are REAL
 *  (stand_in=false) and count toward the calibration floor. */
export async function importGroundTruthCsv(
  file: File
): Promise<GroundTruthImportSummary> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/ground-truth/import`, {
    method: "POST",
    body: form,
    cache: "no-store",
  });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** The exact CSV header a customer produces for a ground-truth import. */
export async function groundTruthTemplate(): Promise<string> {
  const res = await fetch(`${API_BASE}/ground-truth/import/template`, {
    cache: "no-store",
  });
  if (!res.ok) throw await toError(res);
  return res.text();
}

// ── admin (members & roles, audit log) ──

export interface Member {
  id: number;
  email: string;
  role: string; // platform role (viewer | analyst | admin | superadmin)
  org_id: string | null;
  org_role: string | null;
  auth_provider: string | null;
  created_at: string | null;
}

export async function listMembers(): Promise<{
  users: Member[];
  next_cursor: number | null;
  has_more: boolean;
}> {
  return getJson(`/admin/users`);
}

/** Assignable platform roles (superadmin is provisioned out-of-band). */
export const ASSIGNABLE_ROLES = ["viewer", "analyst", "admin"] as const;

export async function updateMemberRole(
  userId: number,
  role: string
): Promise<{ id: number; email: string; role: string }> {
  return sendJson(`/admin/users/${userId}/role`, "PATCH", { role });
}

export interface AuditEntry {
  id: number;
  timestamp: string | null;
  user_id: number | null;
  user_email: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  detail: Record<string, unknown> | null;
  result_summary: string | null;
}

export interface UsageSummary {
  window_days: number;
  since: string | null;
  until: string | null;
  org_id: string | null;
  counts: {
    analyses: number;
    cost_decisions: number;
    usage_events: number;
    webhook_deliveries: number;
  };
  event_counts: Record<string, number>;
  webhook_status_counts: Record<string, number>;
}

export async function getUsageSummary(days = 30): Promise<UsageSummary> {
  return getJson(`/admin/usage-summary?days=${encodeURIComponent(String(days))}`);
}

export interface WebhookDelivery {
  id: number;
  batch_id: number;
  batch_ulid: string;
  event_type: string;
  status: string;
  attempts: number;
  response_code: number | null;
  created_at: string | null;
  last_attempt_at: string | null;
  next_retry_at: string | null;
}

export async function listWebhookDeliveries(limit = 20): Promise<{
  deliveries: WebhookDelivery[];
}> {
  return getJson(`/admin/webhook-deliveries?limit=${encodeURIComponent(String(limit))}`);
}

/** Query the immutable audit log over a bounded range (backend requires start &
 *  end; max 90 days). Defaults to the last 30 days. */
export async function getAuditLog(days = 30): Promise<{
  entries: AuditEntry[];
  next_cursor: string | null;
  has_more: boolean;
}> {
  const { start, end } = auditRange(days);
  const q = `start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&limit=50`;
  return getJson(`/admin/audit-log?${q}`);
}

/** The same-origin URL for a CSV export of the audit log (a real download). */
export function auditLogCsvUrl(days = 30): string {
  const { start, end } = auditRange(days);
  return `${API_BASE}/admin/audit-log?start=${encodeURIComponent(
    start
  )}&end=${encodeURIComponent(end)}&format=csv`;
}

/** ISO range for the audit query, with an explicit `+00:00` offset instead of a
 *  bare `Z`. Python's `datetime.fromisoformat` on the local 3.9 venv rejects the
 *  `Z` suffix (3.12 accepts it) — the offset form parses on every version AND
 *  stays timezone-aware to match the DB's timestamptz column. */
function auditRange(days: number): { start: string; end: string } {
  const now = Date.now();
  const iso = (ms: number) => new Date(ms).toISOString().replace("Z", "+00:00");
  return { start: iso(now - days * 24 * 60 * 60 * 1000), end: iso(now) };
}

// ── developer keys (real; also surfaced at /settings/developer) ──

export interface ApiKey {
  id: number;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export async function listKeys(): Promise<ApiKey[]> {
  return getJson(`/keys`);
}

// ── payload readers (honest extraction from a governed rate card) ──

export interface RateEntry {
  key: string;
  value: string;
}

const RATE_SCALAR_LABELS: Record<string, string> = {
  labor_rate: "labor_rate",
  margin: "margin",
  overhead: "overhead",
  utilization: "utilization",
  region: "region",
  stock_allowance: "stock_allowance",
};

function fmtRate(key: string, v: unknown): string {
  if (typeof v === "number") {
    if (key === "labor_rate" || key === "overhead") return `$${v.toFixed(2)}/hr`;
    if (key === "margin" || key === "utilization") return v.toFixed(2);
    return String(v);
  }
  return String(v);
}

/** Pull the human-readable scalar rates out of a governed card's payload. Reads
 *  ONLY keys that are present — never invents a value. Returns [] when the
 *  payload is absent (→ the caller shows the honest default-table state). */
export function readCardRates(payload: unknown): RateEntry[] {
  if (!payload || typeof payload !== "object") return [];
  const p = payload as Record<string, unknown>;
  const out: RateEntry[] = [];
  for (const [key, label] of Object.entries(RATE_SCALAR_LABELS)) {
    if (p[key] != null && (typeof p[key] === "number" || typeof p[key] === "string")) {
      out.push({ key: label, value: fmtRate(key, p[key]) });
    }
  }
  // Machine hourly rates (map of process → $/hr), if the card carries them.
  const mr = p["machine_rates"];
  if (mr && typeof mr === "object") {
    for (const [proc, v] of Object.entries(mr as Record<string, unknown>)) {
      if (typeof v === "number") out.push({ key: proc, value: `$${v.toFixed(0)}/hr` });
    }
  }
  return out;
}

/** Count material prices the card overrides (a real, honest headline number). */
export function countMaterialPrices(payload: unknown): number {
  if (!payload || typeof payload !== "object") return 0;
  const mp = (payload as Record<string, unknown>)["material_prices"];
  if (mp && typeof mp === "object") return Object.keys(mp as object).length;
  return 0;
}
