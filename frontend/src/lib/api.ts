import { toast } from "sonner";
import * as Sentry from "@sentry/nextjs";
import { apiProblemDetail, apiRecoveryMessage } from "@/lib/api-recovery";
import { API_BASE, browserOrBackendUrl } from "./api-base";
import type { AnalysisListRow } from "./recent-parts";
import type { CostDisposition } from "./cost-disposition";

export interface GeometryInfo {
  vertices: number;
  faces: number;
  volume_mm3: number;
  surface_area_mm2: number;
  bounding_box_mm: [number, number, number];
  is_watertight: boolean;
  is_manifold: boolean;
  center_of_mass: [number, number, number];
  units: string;
}

/**
 * A structured manufacturing-standard reference, serialized by the backend
 * (`serialize_citation`) as `{standard?, clause?, text?, rule_id?}` with every
 * null field DROPPED. The honesty contract that governs the render:
 *
 *   • `standard` PRESENT  → a real source (AMS/ASTM/ISO/NADCA/vendor guide);
 *     render it as a citation chip (`standard` + optional `clause`).
 *   • `standard` ABSENT   → the descriptor case: the analyzer's `cite=` string
 *     did not parse to a real source, so only `text` survives. Render it as
 *     plain descriptive text — NEVER promote a descriptor to a fake citation.
 *
 * The whole `citation` key is omitted when the issue is genuinely uncited.
 */
export interface IssueCitation {
  standard?: string;
  clause?: string;
  text?: string;
  rule_id?: string;
}

export interface Issue {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
  fix_suggestion: string | null;
  process?: string;
  /** TRUE total of affected faces (no longer clipped by the analyzers). */
  affected_face_count?: number;
  /** up to MAX_SERIALIZED_AFFECTED_FACES (2000) indices for the 3D highlight. */
  affected_faces_sample?: number[];
  /** set by the serializer when affected_face_count > 2000: the sample is capped,
   *  the honest total is still in affected_face_count (nothing silently dropped). */
  affected_faces_truncated?: boolean;
  region_center?: [number, number, number];
  measured_value?: number;
  required_value?: number;
  /** structured standard reference; absent when the issue is uncited. */
  citation?: IssueCitation;
  /** "localized" when the finding has faces or a region center; "whole_part"
   *  when it is honestly unlocalizable (no faked location). */
  scope?: "localized" | "whole_part";
}

export interface Segment {
  id: number;
  type: string;
  face_count: number;
  centroid: [number, number, number];
  confidence: number;
}

export interface ProcessScore {
  process: string;
  score: number;
  verdict: "pass" | "issues" | "fail";
  recommended_material: string | null;
  recommended_machine: string | null;
  estimated_cost_factor: number | null;
  /** the analyzer's standards bibliography (AMS/ASTM/ISO/NADCA/vendor) behind
   *  this process's thresholds; [] when the analyzer declares none. */
  standards?: string[];
  issues: Issue[];
}

export interface PriorityFix {
  code: string;
  severity: string;
  message: string;
  process: string;
  fix: string | null;
  measured_value: number | null;
  required_value: number | null;
}

export interface FeatureInfo {
  kind: string;
  face_count: number;
  centroid: [number, number, number];
  radius: number | null;
  depth: number | null;
  area: number | null;
  confidence: number;
}

export interface RulePackInfo {
  name: string;
  version: string;
  description: string;
  override_count: number;
  mandatory_issue_count: number;
}

/**
 * Opt-in per-face wall-thickness map for a thin-wall heatmap. Returned under
 * `wall_thickness_map` ONLY when the request passed `include_thickness=true`
 * (never persisted/cached). `values[i]` is the inward-ray wall thickness (mm) of
 * analyzed-mesh face `i` — the SAME index space as `Issue.affected_faces_sample`
 * — or `null` where thickness is uncomputable (open/degenerate face). When the
 * analyzed mesh was decimated, `decimated` is true and indices map to the
 * approximated geometry, not the original upload.
 */
export interface WallThicknessMap {
  n_faces: number;
  units: string; // "mm"
  values: (number | null)[];
  note: string;
  decimated?: boolean;
  original_faces?: number;
}

export interface ValidationResult {
  filename: string;
  file_type: string;
  overall_verdict: "pass" | "issues" | "fail" | "unknown";
  best_process: string | null;
  analysis_time_ms: number;
  geometry: GeometryInfo;
  segments: Segment[];
  universal_issues: Issue[];
  process_scores: ProcessScore[];
  priority_fixes: PriorityFix[];
  features?: FeatureInfo[];
  rule_pack?: { name: string; version: string };
  /** present only when the analysis was requested with include_thickness. */
  wall_thickness_map?: WallThicknessMap;
  /** Present when an inch-authored unitless mesh was explicitly declared. */
  source_units?: {
    declared: "inch";
    scale_to_mm: number;
    provenance: "USER";
    note: string;
  };
}

export interface Material {
  name: string;
  processes: string[];
  min_wall_mm: number;
  tensile_mpa: number | null;
  cost_per_kg_usd: number | null;
  notes: string;
}

export interface Machine {
  name: string;
  manufacturer: string;
  process: string;
  build_volume_mm: [number, number, number];
  min_layer_mm: number | null;
  materials: string[];
  notes: string;
}

/* ------------------------------------------------------------------ */
/*  Analysis history types (Phase 3 — PERS-09)                        */
/* ------------------------------------------------------------------ */

export interface AnalysisSummary {
  id: number;
  ulid: string;
  filename: string;
  file_type: string;
  overall_verdict: "pass" | "issues" | "fail" | "unknown";
  face_count: number;
  analysis_time_ms: number;
  created_at: string;
}

export interface AnalysisDetail {
  id: number;
  ulid: string;
  filename: string;
  file_type: string;
  overall_verdict: "pass" | "issues" | "fail" | "unknown";
  face_count: number;
  analysis_time_ms: number;
  created_at: string;
  result_json: ValidationResult;
  is_public: boolean;
  share_url: string | null;
}

export interface RateLimits {
  remaining: number;
  limit: number;
  reset: number;
}

export interface AnalysesPage {
  analyses: AnalysisSummary[];
  next_cursor: string | null;
  has_more: boolean;
  rateLimits?: RateLimits;
}

/* ------------------------------------------------------------------ */
/*  Share types (Phase 4 — SHARE-01..05)                              */
/* ------------------------------------------------------------------ */

export interface SharedAnalysis {
  filename: string;
  file_type: string;
  verdict: string;
  face_count: number;
  duration_ms: number;
  created_at: string;
  process_scores: ProcessScore[];
  universal_issues: Issue[];
  geometry: GeometryInfo;
  best_process: string | null;
  priority_fixes: PriorityFix[];
}

/* ------------------------------------------------------------------ */
/*  Mesh Repair types (Phase 5 — REPAIR-01..03)                       */
/* ------------------------------------------------------------------ */

export interface RepairDetails {
  tier?: "trimesh" | "pymeshfix";
  original_faces?: number;
  repaired_faces?: number;
  holes_filled?: number;
  duration_ms?: number;
  error?: string;
}

export interface RepairResult {
  original_analysis: ValidationResult;
  repair_applied: boolean;
  repair_details: RepairDetails;
  repaired_analysis: ValidationResult | null;
  repaired_file_b64: string | null;
}

/* ------------------------------------------------------------------ */
/*  Auth + rate-limit helpers                                          */
/* ------------------------------------------------------------------ */

function extractRateLimits(headers: Headers): RateLimits | undefined {
  const remaining = headers.get("X-RateLimit-Remaining");
  const limit = headers.get("X-RateLimit-Limit");
  if (!remaining || !limit) return undefined;
  return {
    remaining: parseInt(remaining, 10),
    limit: parseInt(limit, 10),
    reset: parseInt(headers.get("X-RateLimit-Reset") || "0", 10),
  };
}

// Module-level rate-limit state — updated by every apiClient response
let _latestRateLimits: RateLimits | undefined;

export function getLatestRateLimits(): RateLimits | undefined {
  return _latestRateLimits;
}

/* ------------------------------------------------------------------ */
/*  Centralized API client                                             */
/* ------------------------------------------------------------------ */

/**
 * Centralized API client — attaches auth headers, extracts rate limits,
 * handles errors (timeout, malformed JSON, 5xx retry, 429 toast, 4xx throw).
 */
const apiClient = {
  async fetch(
    url: string,
    options: RequestInit = {},
    { retries = 0, retryDelayMs = 1000 }: { retries?: number; retryDelayMs?: number } = {}
  ): Promise<Response> {
    // Same-origin → the httpOnly session cookie is sent automatically and the
    // Next proxy forwards it to the backend. No Authorization header needed.
    const headers = new Headers(options.headers);

    let lastError: Error | null = null;
    for (let attempt = 0; attempt <= retries; attempt++) {
      if (attempt > 0) {
        await new Promise((r) => setTimeout(r, retryDelayMs * attempt));
      }

      let res: Response;
      try {
        res = await fetch(url, { ...options, headers });
      } catch (err) {
        // Network error / timeout
        lastError = err instanceof Error ? err : new Error(String(err));
        if (attempt === retries) {
          toast.error("Connection timed out. Check your network.");
          throw lastError;
        }
        continue;
      }

      // Extract rate limits from every response
      const rl = extractRateLimits(res.headers);
      if (rl) _latestRateLimits = rl;

      // 429 — rate limited, no retry
      if (res.status === 429) {
        const retryAfter = parseInt(res.headers.get("Retry-After") || "60", 10);
        toast.error(`Rate limit exceeded. Try again in ${retryAfter}s.`);
        const err = await res.json().catch(() => ({ detail: "Rate limit exceeded" }));
        throw new Error(
          apiRecoveryMessage({
            status: 429,
            payload: err,
            resource: "verification",
            retryAfter: String(retryAfter),
          }),
        );
      }

      // 5xx — retry with backoff
      if (res.status >= 500) {
        const problem = await res.clone().json().catch(() => null);
        lastError = new Error(
          apiRecoveryMessage({
            status: res.status,
            payload: problem,
            resource: "verification",
            retryAfter: res.headers.get("retry-after"),
          }),
        );
        if (attempt === retries) {
          toast.error("Server error. We've been notified.");
          Sentry.captureException(lastError, { extra: { url, status: res.status } });
          throw lastError;
        }
        continue;
      }

      // 4xx (non-429) — no retry
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(
          apiProblemDetail(err) ||
            apiRecoveryMessage({ status: res.status, payload: err, resource: "verification" }),
        );
      }

      return res;
    }
    throw lastError || new Error("Request failed");
  },

  async fetchJson<T>(url: string, options: RequestInit = {}): Promise<T> {
    const res = await this.fetch(url, options, { retries: 2, retryDelayMs: 1000 });
    try {
      return await res.json();
    } catch {
      Sentry.captureMessage("Malformed JSON response", { extra: { url } });
      toast.error("Unexpected server response.");
      throw new Error("Unexpected server response");
    }
  },
};

/* ------------------------------------------------------------------ */
/*  API functions                                                      */
/* ------------------------------------------------------------------ */

export async function validateFile(
  file: File,
  processes?: string[],
  rulePack?: string,
  /** opt-in: request the per-face wall-thickness map for a thin-wall heatmap.
   *  Off by default → no query param → response is byte-identical to before. */
  includeThickness?: boolean,
  sourceUnits?: "mm" | "inch"
): Promise<ValidationResult> {
  const formData = new FormData();
  formData.append("file", file);

  const params = new URLSearchParams();
  if (processes && processes.length > 0) {
    params.set("processes", processes.join(","));
  }
  if (rulePack) {
    params.set("rule_pack", rulePack);
  }
  if (includeThickness) {
    params.set("include_thickness", "true");
  }
  if (sourceUnits) {
    params.set("units", sourceUnits);
  }

  let url = `${API_BASE}/validate`;
  const qs = params.toString();
  if (qs) {
    url += `?${qs}`;
  }

  return apiClient.fetchJson<ValidationResult>(url, { method: "POST", body: formData });
}

export async function validateQuick(file: File): Promise<{
  filename: string;
  verdict: string;
  geometry: Partial<GeometryInfo>;
  issues: Issue[];
}> {
  const formData = new FormData();
  formData.append("file", file);
  return apiClient.fetchJson(`${API_BASE}/validate/quick`, {
    method: "POST",
    body: formData,
  });
}

export async function getProcesses(): Promise<{ processes: Array<{ process: string; material_count: number; machine_count: number; materials: string[]; machines: string[] }> }> {
  return apiClient.fetchJson(`${API_BASE}/processes`);
}

export async function getMaterials(): Promise<{ materials: Material[] }> {
  return apiClient.fetchJson(`${API_BASE}/materials`);
}

export async function getMachines(): Promise<{ machines: Machine[] }> {
  return apiClient.fetchJson(`${API_BASE}/machines`);
}

export async function getRulePacks(): Promise<{ rule_packs: RulePackInfo[] }> {
  return apiClient.fetchJson(`${API_BASE}/rule-packs`);
}

/* ------------------------------------------------------------------ */
/*  Analysis history client functions (Phase 3 — PERS-09)             */
/* ------------------------------------------------------------------ */

export async function fetchAnalyses(params: {
  cursor?: string;
  limit?: number;
  verdict?: string;
}): Promise<AnalysesPage> {
  const url = new URL(`${API_BASE}/analyses`, window.location.origin);
  if (params.cursor) url.searchParams.set("cursor", params.cursor);
  if (params.limit) url.searchParams.set("limit", String(params.limit));
  if (params.verdict) url.searchParams.set("verdict", params.verdict);

  const res = await apiClient.fetch(url.toString());
  const rateLimits = getLatestRateLimits();
  const data = await res.json();
  return { ...data, rateLimits };
}

/**
 * Fetch the most recent analyses for the landing "recent parts" strip, typed to
 * the REAL list-endpoint shape (`AnalysisListRow`) rather than the legacy
 * `AnalysisSummary` that mistypes the row (see `lib/recent-parts.ts`). Returns
 * only the honest rows; the strip needs no pagination/rate-limit envelope.
 */
export async function fetchRecentAnalyses(
  limit: number
): Promise<AnalysisListRow[]> {
  const url = new URL(`${API_BASE}/analyses`, window.location.origin);
  url.searchParams.set("limit", String(limit));

  const res = await apiClient.fetch(url.toString());
  const data = (await res.json()) as { analyses?: AnalysisListRow[] };
  return data.analyses ?? [];
}

/* ------------------------------------------------------------------ */
/*  Share client functions (Phase 4 — SHARE-01..05)                    */
/* ------------------------------------------------------------------ */

export async function shareAnalysis(
  id: string
): Promise<{ share_url: string; share_short_id: string }> {
  return apiClient.fetchJson(`${API_BASE}/analyses/${id}/share`, {
    method: "POST",
  });
}

export async function unshareAnalysis(id: string): Promise<void> {
  await apiClient.fetch(`${API_BASE}/analyses/${id}/share`, {
    method: "DELETE",
  });
}

export async function fetchSharedAnalysis(
  shortId: string
): Promise<SharedAnalysis> {
  // Public endpoint — no auth needed, but still benefits from error handling
  const res = await fetch(browserOrBackendUrl(`/s/${shortId}`));
  if (!res.ok) {
    throw new Error(
      res.status === 404 ? "Shared analysis not found" : "Failed to fetch"
    );
  }
  return res.json();
}

/* ------------------------------------------------------------------ */
/*  PDF download (Phase 4 — PDF-05)                                    */
/* ------------------------------------------------------------------ */

export async function downloadPdf(
  analysisId: string,
  filename: string
): Promise<void> {
  const res = await apiClient.fetch(`${API_BASE}/analyses/${analysisId}/pdf`);
  const blob = await res.blob();
  const stem = filename.replace(/\.[^.]+$/, "");
  const downloadName = `${stem}-dfm-report.pdf`;

  // Create temporary download link
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = downloadName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/* ------------------------------------------------------------------ */
/*  Mesh Repair client (Phase 5 — REPAIR-01..03)                      */
/* ------------------------------------------------------------------ */

export async function repairAnalysis(
  file: File,
  processes?: string[],
  rulePack?: string
): Promise<RepairResult> {
  const formData = new FormData();
  formData.append("file", file);

  const params = new URLSearchParams();
  if (processes && processes.length > 0) {
    params.set("processes", processes.join(","));
  }
  if (rulePack) {
    params.set("rule_pack", rulePack);
  }

  let url = `${API_BASE}/validate/repair`;
  const qs = params.toString();
  if (qs) {
    url += `?${qs}`;
  }

  return apiClient.fetchJson<RepairResult>(url, {
    method: "POST",
    body: formData,
  });
}

export async function fetchAnalysis(id: string): Promise<AnalysisDetail> {
  return apiClient.fetchJson<AnalysisDetail>(`${API_BASE}/analyses/${id}`);
}

/* ------------------------------------------------------------------ */
/*  Image-to-Mesh Reconstruction (Phase 10 — IMG-05)                   */
/* ------------------------------------------------------------------ */

export interface ReconstructionSubmitResult {
  job_id: string;
  status: string;
  poll_url: string;
  estimated_seconds: number;
}

export interface JobStatus {
  job_id: string;
  status: "queued" | "running" | "done" | "failed";
  progress?: number;
  result?: Record<string, unknown>;
  error?: string;
}

export async function submitReconstruction(
  images: File[],
  processTypes?: string,
  rulePack?: string
): Promise<ReconstructionSubmitResult> {
  const form = new FormData();
  images.forEach((img) => form.append("images", img));
  if (processTypes) form.append("process_types", processTypes);
  if (rulePack) form.append("rule_pack", rulePack);

  return apiClient.fetchJson<ReconstructionSubmitResult>(
    `${API_BASE}/reconstruct`,
    { method: "POST", body: form }
  );
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  return apiClient.fetchJson<JobStatus>(`${API_BASE}/jobs/${jobId}`);
}

export function getReconstructionMeshUrl(jobId: string): string {
  return `${API_BASE}/reconstructions/${jobId}/mesh.stl`;
}

/* ------------------------------------------------------------------ */
/*  Cost decision client (Cycle 5 — POST /api/v1/validate/cost)        */
/*  Types mirror src/costing/report.py::report_to_dict exactly.        */
/*  NOTE: recommendation / if_redesigned are keyed by quantity but      */
/*  JSON-serialize the int keys as strings -> Record<string, …>.        */
/* ------------------------------------------------------------------ */

export type Provenance = "MEASURED" | "SHOP" | "USER" | "DEFAULT";

export interface CostDriver {
  name: string;
  value: number;
  unit: string;
  provenance: Provenance;
  source: string;
  error_band_pct: number | null;
}

/**
 * Confidence interval around a should-cost. `validated:false` (today, for every
 * part — no ground truth yet) → `method:"assumption-band"` and `label` reads
 * "assumption-based, not yet validated". Flips to `"measured-residual"` /
 * `validated:true` only when real residuals accrue. The UI renders this honesty
 * VERBATIM and never prints a fabricated ±X% accuracy number.
 *
 * Lives in the engine's report_to_dict; surfaced through the API is a build gap.
 */
export interface CostConfidence {
  low_usd: number;
  high_usd: number;
  point_usd: number;
  level: number; // e.g. 0.8
  method: "assumption-band" | "measured-residual";
  validated: boolean;
  n_samples: number;
  half_width_pct: number;
  basis: string;
  label: string;
}

/**
 * Geometric routing: the archetype + recommended process + the human reasoning
 * paragraph (the trust object for the manufacturing engineer), plus the measured
 * drivers that decided it. Lives in the engine; surfacing it is a build gap.
 */
export interface CostRouting {
  archetype: string;
  recommended_process: string;
  eval_family: string;
  material_hint: string;
  confidence: number;
  reasoning: string;
  alternatives: string[];
  drivers: Record<string, number | boolean>;
}

export interface CostLeadTime {
  low_days: number;
  high_days: number;
  mid_days: number;
  components: Record<string, number>;
  capacity:
    | { n_machines?: number; machine_hours_per_day?: number; provenance?: string }
    | Record<string, never>;
}

export interface CostEstimate {
  process: string;
  material: string;
  quantity: number;
  unit_cost_usd: number;
  fixed_cost_usd: number;
  variable_cost_usd: number;
  est_error_band_pct: number;
  /** confidence interval (engine field; optional until surfaced through the API). */
  confidence?: CostConfidence;
  dfm_ready: boolean;
  dfm_verdict: "pass" | "issues" | "fail";
  dfm_score: number;
  /** ERROR-severity blocker MESSAGES (kept for text consumers). */
  dfm_blockers: string[];
  /** The same blockers as FULL serialized Issues — same order/source as
   *  `dfm_blockers` — so a cost-side blocker can locate on the part (faces /
   *  region / measured / citation), not merely restate its message. Absent on
   *  reports produced before the cost-blocker relink. */
  dfm_blocker_details?: Issue[];
  /** True when the declared service environment excludes this process/material pair. */
  environment_excluded?: boolean;
  /** Cited reason for environment_excluded, usually naming the governing standard. */
  environment_exclusion_reason?: string;
  line_items: Record<string, number>;
  drivers: CostDriver[];
  lead_time: CostLeadTime;
}

export interface CostRecommendation {
  process: string;
  material: string;
  unit_cost_usd: number;
  dfm_ready: boolean;
  dfm_verdict: string;
  lead_low_days: number | null;
  lead_high_days: number | null;
}

export interface CostRedesigned {
  process: string;
  material: string;
  unit_cost_usd: number;
  caveat: string;
}

export interface CostDecision {
  make_now_process: string;
  make_now_material: string;
  tooling_process: string | null;
  tooling_dfm_ready: boolean;
  crossover_qty: number | null;
  recommendation: Record<string, CostRecommendation>;
  if_redesigned: Record<string, CostRedesigned | null>;
  note: string;
}

export interface CostAssumption {
  name: string;
  value: number;
  unit: string;
  provenance: Provenance;
  source: string;
}

export interface CostGeometry {
  volume_cm3: number;
  surface_area_cm2: number;
  bbox_mm: [number, number, number];
  watertight: boolean;
  face_count: number;
}

export interface CostFeasibility {
  process: string;
  verdict: string;
  score: number;
  costed: boolean;
}

export interface CostUnitWarning {
  code: string;
  severity: string;
  message: string;
  measured?: {
    volume_cm3?: number;
    max_bbox_mm?: number;
  };
  assumed_units?: string;
  provenance?: string;
}

export interface CostReport {
  filename: string;
  status: "OK" | "GEOMETRY_INVALID";
  reason: string | null;
  geometry: CostGeometry;
  material_class: string;
  quantities: number[];
  estimates: CostEstimate[];
  engine_feasibility: CostFeasibility[];
  /** geometric routing (engine field; optional until surfaced through the API). */
  routing?: CostRouting;
  notes: string[];
  assumptions: CostAssumption[];
  /** Measured-geometry safety rail for unitless CAD. These warnings must stay
   * visible until the user confirms millimetres versus inches and re-costs. */
  unit_warnings?: CostUnitWarning[];
  decision: CostDecision | null;
  /** Persisted machine-fit verdict lattice. Present when the organization has
   *  declared inventory and/or a service environment. This is independent of
   *  the route's DFM status and must remain the authority for makeability copy. */
  verification?: import("@/lib/verify/verification").VerificationBlock | null;
  /**
   * Present when the authed cost route persisted this decision (Phase 2 gap #3).
   * `id` is the durable cost-decision ulid; `url` is its backend detail path.
   * Absent on the demo route or when COST_PERSIST_ENABLED is off.
   */
  saved?: { id: string; url: string };
  /**
   * Retrieval-grounded PART IDENTITY (identity Slice 1): the org's closest PRIOR
   * parts as a provenance-tagged, confidence-scored SUGGESTION to confirm — never
   * an asserted identity. `null` for anonymous / demo / empty-corpus callers (the
   * engine never fabricates an identity with no library to ground it). See
   * `@/lib/verify/identity` for the render-model / IdentityResult shape.
   */
  identity?: import("@/lib/verify/identity").IdentityResult | null;
}

export interface CostOptions {
  qty: string; // comma list e.g. "50,5000"
  region: string; // "auto" | US|EU|MX|CN|IN|SA ("auto" => omit, shop region or US)
  cavities: number; // >= 1
  complexity: string; // simple|moderate|complex|very_complex
  material_class: string; // polymer|aluminum|steel|stainless|titanium
  /** Explicit interpretation for unitless STL/mesh coordinates. */
  units: "mm" | "inch";
  /** per-shop calibration profile id (see getShops). null/undefined => generic defaults. */
  shop?: string | null;
  /**
   * Ad-hoc rate/driver overrides (dotted keys → numbers), e.g.
   * `{ labor_rate: 40, "machine_rate.MJF": 25, "material_price.@polymer": 6.5 }`.
   * Threaded into POST /validate/cost so an edited assumption/driver truly
   * re-costs server-side; the engine tags the touched lines USER.
   */
  overrides?: Record<string, number>;
}

/** A bindable per-shop calibration profile (GET /shops). */
export interface ShopProfileInfo {
  id: string;
  name: string;
  region: string;
  source: string | null;
}

/** List the per-shop calibration profiles available to bind (F1). */
export async function getShops(): Promise<{ shops: ShopProfileInfo[] }> {
  return apiClient.fetchJson<{ shops: ShopProfileInfo[] }>(`${API_BASE}/shops`);
}

/**
 * Thrown when POST /validate/cost returns a 400 GEOMETRY_INVALID. Carries the
 * structured `geometry` summary from the body so the UI can render a repair
 * card (reason + measured geometry) instead of a bare error string. The cost
 * engine's G1 gate refuses broken geometry (volume <= 0 / non-watertight) here.
 */
export class CostGeometryInvalidError extends Error {
  readonly geometry: CostGeometry | null;
  constructor(message: string, geometry: CostGeometry | null) {
    super(message);
    this.name = "CostGeometryInvalidError";
    this.geometry = geometry;
  }
}

/**
 * Submit a CAD file for an explainable should-cost / make-vs-buy decision.
 *
 * The endpoint takes multipart Form fields (not query params). We do NOT route
 * through apiClient.fetch here because the GEOMETRY_INVALID (400) body carries a
 * structured `geometry` payload we want to surface; apiClient consumes the body
 * and throws a flat Error. Instead we replicate apiClient's rate-limit + 429/5xx
 * handling and branch on the structured 400. No auto-retry: costing is
 * non-idempotent compute. The call is authed by the session via the same-origin
 * proxy (`/api/proxy/validate/cost`); no API key in the browser.
 */
async function _costEstimate(
  file: File,
  opts: CostOptions
): Promise<CostReport> {
  const form = new FormData();
  form.append("file", file);
  form.append("qty", opts.qty);
  // "auto" / empty → omit, so a bound shop's own region wins (else backend US).
  if (opts.region && opts.region !== "auto") form.append("region", opts.region);
  form.append("cavities", String(opts.cavities));
  form.append("complexity", opts.complexity);
  form.append("material_class", opts.material_class);
  form.append("units", opts.units);
  // Per-shop calibration (F1): bind the shop's real rates → SHOP-tagged number.
  if (opts.shop) form.append("shop", opts.shop);
  // Ad-hoc overrides (F3): real server re-cost on an edited assumption/driver.
  if (opts.overrides && Object.keys(opts.overrides).length > 0) {
    form.append("overrides", JSON.stringify(opts.overrides));
  }

  const url = `${API_BASE}/validate/cost`;

  let res: Response;
  try {
    res = await fetch(url, { method: "POST", body: form });
  } catch (err) {
    const e = err instanceof Error ? err : new Error(String(err));
    toast.error("Connection failed. Check your network.");
    throw e;
  }

  // Track rate limits on every response, like apiClient does.
  const rl = extractRateLimits(res.headers);
  if (rl) _latestRateLimits = rl;

  if (res.ok) {
    return (await res.json()) as CostReport;
  }

  // Parse the structured error body once (safe fallback if not JSON).
  const body: Record<string, unknown> = await res
    .json()
    .catch(() => ({ message: res.statusText }));

  if (res.status === 429) {
    const retryAfter = parseInt(res.headers.get("Retry-After") || "60", 10);
    toast.error(`Rate limit exceeded. Try again in ${retryAfter}s.`);
    throw new Error(
      (body.message as string) ||
        (body.detail as string) ||
        "Rate limit exceeded"
    );
  }

  if (res.status >= 500) {
    const e = new Error(`Server error ${res.status}`);
    toast.error("Server error. We've been notified.");
    Sentry.captureException(e, { extra: { url, status: res.status } });
    throw e;
  }

  // GEOMETRY_INVALID (400) — structured {code,message,geometry,doc_url}.
  if (body.code === "GEOMETRY_INVALID") {
    throw new CostGeometryInvalidError(
      (body.message as string) || "Geometry invalid — repair required.",
      (body.geometry as CostGeometry) ?? null
    );
  }

  // Other 4xx — structured {code,message,doc_url} or legacy {detail}.
  throw new Error(
    (body.message as string) ||
      (body.detail as string) ||
      `Request failed: ${res.status}`
  );
}

/** Session-authenticated should-cost (via the same-origin proxy). */
export function costEstimate(
  file: File,
  opts: CostOptions
): Promise<CostReport> {
  return _costEstimate(file, opts);
}

/* ------------------------------------------------------------------ */
/*  Cost-decision persistence (Phase 2 gap #3 — save/export/share/compare) */
/*  Contract: outputs/impl/cost-persist-note.md. Base is /api/v1 via the   */
/*  same-origin authed proxy (require_role viewer for reads, analyst for    */
/*  share). result_json.decision keys round-trip as STRINGS through JSONB — */
/*  read them via lib/cost-decision helpers, never as numeric keys.         */
/* ------------------------------------------------------------------ */

/** One row of the cost-decision history list (denormalized for listing). */
export interface CostDecisionGovernance {
  approval_status?: "unreviewed" | "approved" | string;
  approved_by_user_id?: number | null;
  approved_at?: string | null;
  approval_note?: string | null;
  is_stale?: boolean;
  stale_at?: string | null;
  stale_reason?: string | null;
  user_disposition?: CostDisposition | null;
  user_disposition_label?: string | null;
  disposition_note?: string | null;
  disposition_updated_at?: string | null;
  disposition_updated_by_user_id?: number | null;
}

export interface CostDecisionSummary extends CostDecisionGovernance {
  id: string;
  filename: string;
  file_type: string;
  label: string | null;
  make_now_process: string | null;
  crossover_qty: number | null;
  quantities: number[];
  created_at: string;
  is_public: boolean;
  share_url: string | null;
}

export interface CostDecisionsPage {
  cost_decisions: CostDecisionSummary[];
  next_cursor: string | null;
  has_more: boolean;
  rateLimits?: RateLimits;
}

/** Full saved decision envelope — `result` is the verbatim report_to_dict. */
export interface CostDecisionDetail extends CostDecisionGovernance {
  id: string;
  filename: string;
  file_type: string;
  label: string | null;
  created_at: string;
  engine_version: string | null;
  make_now_process: string | null;
  crossover_qty: number | null;
  quantities: number[];
  is_public: boolean;
  share_url: string | null;
  result: CostReport;
}

/**
 * Sanitized public cost-decision payload (GET /s/cost/{short_id}). ZERO owner
 * PII — the decision content (provenance + honest confidence band) is intact.
 */
export interface SharedCostDecision {
  filename: string;
  file_type: string;
  label: string | null;
  created_at: string;
  make_now_process: string | null;
  crossover_qty: number | null;
  quantities: number[];
  geometry: CostGeometry;
  material_class: string | null;
  routing: CostRouting | null;
  estimates: CostEstimate[];
  decision: CostDecision | null;
  assumptions: CostAssumption[];
  engine_feasibility: CostFeasibility[];
  notes: string[];
  status: string | null;
}

/** Summary side of a compare (one decision). */
export interface CostCompareSummary {
  id: string;
  filename: string;
  label: string | null;
  make_now_process: string | null;
  make_now_material: string | null;
  tooling_process: string | null;
  crossover_qty: number | null;
  material_class: string | null;
  created_at: string;
}

export interface CostCompareUnitRow {
  quantity: number;
  a: { process: string | null; unit_cost_usd: number | null } | null;
  b: { process: string | null; unit_cost_usd: number | null } | null;
  delta_usd: number | null;
  delta_pct: number | null;
}

/** Structured diff of two owned cost decisions (GET /cost-decisions/compare). */
export interface CostComparison {
  a: CostCompareSummary;
  b: CostCompareSummary;
  unit_cost_by_qty: CostCompareUnitRow[];
  diff: {
    make_now_process: [string | null, string | null];
    tooling_process: [string | null, string | null];
    crossover_qty: [number | null, number | null];
  };
  unit_costs_by_process: {
    a: Record<string, Record<string, number>>;
    b: Record<string, Record<string, number>>;
  };
}

export interface CostShareResult {
  share_url: string;
  share_short_id: string;
}

export interface CostApprovalResult extends CostDecisionGovernance {
  id: string;
}

export interface CostDispositionResult extends CostDecisionGovernance {
  id: string;
  user_disposition: CostDisposition | null;
}

export interface RfqPackageWarning {
  code: string;
  decision_id?: string;
  message: string;
}

export interface RfqPackageSummary {
  id: string;
  title: string;
  supplier_name: string | null;
  status: "generated" | "archived" | string;
  item_count: number;
  approved_count: number;
  stale_count: number;
  unvalidated_count: number;
  raw_cad_included: boolean;
  live_supplier_send: boolean;
  warnings: RfqPackageWarning[];
  metadata: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

export interface RfqPackageDetail extends RfqPackageSummary {
  items: Array<{
    decision: {
      id: string;
      filename: string;
      approval_status: string;
      is_stale: boolean;
      unvalidated_confidence: boolean;
      make_now_process: string | null;
      crossover_qty: number | null;
    };
    declared_part?: Record<string, unknown> | null;
    part_context?: Record<string, unknown> | null;
    raw_cad?: { included: boolean; reason?: string; source?: string } | null;
  }>;
}

export interface RfqPackagesPage {
  packages: RfqPackageSummary[];
}

export async function fetchRfqPackages(limit = 50): Promise<RfqPackagesPage> {
  const url = new URL(`${API_BASE}/rfq-packages`, window.location.origin);
  url.searchParams.set("limit", String(limit));
  return apiClient.fetchJson<RfqPackagesPage>(url.toString());
}

export async function fetchRfqPackage(id: string): Promise<RfqPackageDetail> {
  const body = await apiClient.fetchJson<{ package: RfqPackageDetail }>(
    `${API_BASE}/rfq-packages/${id}`
  );
  return body.package;
}

export async function createRfqPackage(input: {
  decisionIds: string[];
  title?: string;
  supplierName?: string;
  note?: string;
  includeRawCad?: boolean;
}): Promise<RfqPackageDetail> {
  const body = await apiClient.fetchJson<{ package: RfqPackageDetail }>(
    `${API_BASE}/rfq-packages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision_ids: input.decisionIds,
        title: input.title?.trim() || null,
        supplier_name: input.supplierName?.trim() || null,
        note: input.note?.trim() || null,
        include_raw_cad: Boolean(input.includeRawCad),
      }),
    }
  );
  return body.package;
}

/** Paginated list of the user's saved cost decisions. */
export async function fetchCostDecisions(params: {
  cursor?: string;
  limit?: number;
  process?: string;
  createdAfter?: string;
  createdBefore?: string;
}): Promise<CostDecisionsPage> {
  const url = new URL(`${API_BASE}/cost-decisions`, window.location.origin);
  if (params.cursor) url.searchParams.set("cursor", params.cursor);
  if (params.limit) url.searchParams.set("limit", String(params.limit));
  if (params.process) url.searchParams.set("process", params.process);
  if (params.createdAfter) url.searchParams.set("created_after", params.createdAfter);
  if (params.createdBefore) url.searchParams.set("created_before", params.createdBefore);

  const res = await apiClient.fetch(url.toString());
  const rateLimits = getLatestRateLimits();
  const data = await res.json();
  return { ...data, rateLimits };
}

/** Full saved cost decision by id (owner-scoped; 404 for others). */
export async function fetchCostDecision(id: string): Promise<CostDecisionDetail> {
  return apiClient.fetchJson<CostDecisionDetail>(`${API_BASE}/cost-decisions/${id}`);
}

/** Approve/sign off a saved cost decision without changing its artifact JSON. */
export async function approveCostDecision(
  id: string,
  note?: string
): Promise<CostApprovalResult> {
  return apiClient.fetchJson<CostApprovalResult>(
    `${API_BASE}/cost-decisions/${id}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: note?.trim() || null }),
    }
  );
}

/** Reopen a saved cost decision's signoff while keeping the artifact immutable. */
export async function reopenCostDecisionApproval(
  id: string
): Promise<CostApprovalResult> {
  return apiClient.fetchJson<CostApprovalResult>(
    `${API_BASE}/cost-decisions/${id}/approve`,
    { method: "DELETE" }
  );
}

/** Persist or withdraw the human four-way outcome on a saved decision. */
export async function setCostDecisionDisposition(
  id: string,
  disposition: CostDisposition | null,
  note?: string
): Promise<CostDispositionResult> {
  return apiClient.fetchJson<CostDispositionResult>(
    `${API_BASE}/cost-decisions/${id}/disposition`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        disposition,
        note: disposition ? note?.trim() || null : null,
      }),
    }
  );
}

/* ------------------------------------------------------------------ */
/*  Catalog — the org-scoped parts×decisions grid (W1.4, GET /catalog) */
/*  The lakehouse read surface the FE-4 catalog door consumes instead   */
/*  of joining /analyses + /cost-decisions on the client. Every field    */
/*  mirrors backend/src/api/catalog.py + catalog_service.derive_row      */
/*  VERBATIM — a value the endpoint does not carry is null, never faked.  */
/* ------------------------------------------------------------------ */

/**
 * The recommended make route for a catalog part. `source` distinguishes a
 * costed decision's make-now route (`"costed"`) from a raw DFM suggestion on a
 * part that has not been costed yet (`"dfm"`).
 */
export interface CatalogRoute {
  process: string;
  material: string | null;
  source: "costed" | "dfm";
}

/**
 * Unit cost for a catalog row's recommended route. `usd` is null and `withheld`
 * true on a DFM-blocked route — the grid never prints a make-price for a part
 * that can't be made as-designed. `validated` rides the engine confidence band
 * (false for every assumption-based band today — no ground truth yet).
 */
export interface CatalogUnitCost {
  usd: number | null;
  qty: number | null;
  currency: string;
  withheld: boolean;
  withheld_reason: string | null;
  validated: boolean;
}

/**
 * Route-scoped DFM finding counts. Null when the part has no analysis (a cost
 * decision alone does not embed the DFM Issue array) — an honest absence, never
 * faked as zero.
 */
export interface CatalogFindings {
  total: number;
  critical: number;
  advisory: number;
  info: number;
  scoped_process: string;
}

/** Provenance mix across the make-now estimate's drivers (server-derived). */
export interface CatalogPosture {
  measured: number;
  shop: number;
  user: number;
  default: number;
  total: number;
  grounded: number;
  guess: number;
  grounded_pct: number;
}

/** A link to a source artifact (the analysis or the cost decision) for a part. */
export interface CatalogRef {
  id: string;
  url: string;
}

/** One catalog grid row — one part (distinct mesh) in the caller's org. */
export interface CatalogRowApi {
  part_key: string;
  filename: string;
  file_type: string;
  lifecycle_state: "Drafted" | "Costed";
  recommended_route: CatalogRoute | null;
  unit_cost: CatalogUnitCost | null;
  findings: CatalogFindings | null;
  provenance_posture: CatalogPosture | null;
  route_blocker_count: number;
  cost_decision: CatalogRef | null;
  analysis: CatalogRef | null;
  updated_at: string;
}

export interface CatalogPagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_more: boolean;
}

/** Facet summary over the FULL org catalog (pre-filter) — real counts. */
export interface CatalogFacets {
  state: Record<string, number>;
  route: Record<string, number>;
  findings: { with_findings: number; without_findings: number; unknown: number };
}

/** The filters the server actually applied (echoed back, canonicalized). */
export interface CatalogFilters {
  state: string | null;
  route: string | null;
  has_findings: boolean | null;
}

export interface CatalogPage {
  rows: CatalogRowApi[];
  pagination: CatalogPagination;
  facets: CatalogFacets;
  /** true when the org exceeded the scan cap and some older parts were omitted. */
  truncated: boolean;
  filters: CatalogFilters;
  rateLimits?: RateLimits;
}

export interface CatalogQuery {
  page?: number;
  pageSize?: number;
  state?: "Drafted" | "Costed" | null;
  route?: string | null;
  hasFindings?: boolean | null;
}

/** Paginated org-scoped catalog grid (GET /api/v1/catalog). */
export async function fetchCatalog(params: CatalogQuery = {}): Promise<CatalogPage> {
  const url = new URL(`${API_BASE}/catalog`, window.location.origin);
  if (params.page) url.searchParams.set("page", String(params.page));
  if (params.pageSize) url.searchParams.set("page_size", String(params.pageSize));
  if (params.state) url.searchParams.set("state", params.state);
  if (params.route) url.searchParams.set("route", params.route);
  if (params.hasFindings != null) {
    url.searchParams.set("has_findings", String(params.hasFindings));
  }
  const res = await apiClient.fetch(url.toString());
  const rateLimits = getLatestRateLimits();
  const data = await res.json();
  return { ...data, rateLimits };
}

/** Trigger a browser download of `blob` as `filename` (shared by the exporters). */
function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function costStem(filename: string): string {
  return filename.replace(/\.[^.]+$/, "");
}

/** Download the cost-report PDF for a saved decision. */
export async function downloadCostPdf(id: string, filename: string): Promise<void> {
  const res = await apiClient.fetch(`${API_BASE}/cost-decisions/${id}/pdf`);
  triggerBlobDownload(await res.blob(), `${costStem(filename)}-cost-report.pdf`);
}

/** Export the raw glass-box decision JSON (result_json) for a saved decision. */
export async function exportCostJson(id: string, filename: string): Promise<void> {
  const res = await apiClient.fetch(`${API_BASE}/cost-decisions/${id}/export.json`);
  triggerBlobDownload(await res.blob(), `${costStem(filename)}-cost.json`);
}

/** Export the estimates / line-items table as CSV (honest confidence columns). */
export async function exportCostCsv(id: string, filename: string): Promise<void> {
  const res = await apiClient.fetch(`${API_BASE}/cost-decisions/${id}/export.csv`);
  triggerBlobDownload(await res.blob(), `${costStem(filename)}-cost.csv`);
}

/** Download a generated RFQ/supplier evidence ZIP. */
export async function downloadRfqPackage(id: string, title?: string | null): Promise<void> {
  const res = await apiClient.fetch(`${API_BASE}/rfq-packages/${id}/download.zip`);
  triggerBlobDownload(await res.blob(), `${costStem(title || "rfq-package")}-rfq.zip`);
}

/** Create a public share link for a saved cost decision (idempotent). */
export async function shareCostDecision(id: string): Promise<CostShareResult> {
  return apiClient.fetchJson<CostShareResult>(`${API_BASE}/cost-decisions/${id}/share`, {
    method: "POST",
  });
}

/** Revoke a cost decision's public share link. */
export async function unshareCostDecision(id: string): Promise<void> {
  await apiClient.fetch(`${API_BASE}/cost-decisions/${id}/share`, { method: "DELETE" });
}

/** Public sanitized cost-decision view (no auth). Mirrors fetchSharedAnalysis. */
export async function fetchSharedCostDecision(
  shortId: string
): Promise<SharedCostDecision> {
  const res = await fetch(browserOrBackendUrl(`/s/cost/${shortId}`));
  if (!res.ok) {
    throw new Error(
      res.status === 404 ? "Shared cost decision not found" : "Failed to fetch"
    );
  }
  return res.json();
}

/** Structured side-by-side diff of two owned cost decisions. */
export async function compareCostDecisions(
  idA: string,
  idB: string
): Promise<CostComparison> {
  const ids = encodeURIComponent(`${idA},${idB}`);
  return apiClient.fetchJson<CostComparison>(
    `${API_BASE}/cost-decisions/compare?ids=${ids}`
  );
}
