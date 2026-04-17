import { toast } from "sonner";
import * as Sentry from "@sentry/nextjs";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

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

export interface Issue {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
  fix_suggestion: string | null;
  process?: string;
  affected_face_count?: number;
  affected_faces_sample?: number[];
  region_center?: [number, number, number];
  measured_value?: number;
  required_value?: number;
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

function authHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const key = localStorage.getItem("cadverify_api_key");
  return key ? { Authorization: `Bearer ${key}` } : {};
}

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
    const headers = new Headers(options.headers);
    // Attach auth header if not already present
    const auth = authHeaders();
    if (auth.Authorization) {
      headers.set("Authorization", auth.Authorization);
    }

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
        throw new Error(err.detail || "Rate limit exceeded");
      }

      // 5xx — retry with backoff
      if (res.status >= 500) {
        lastError = new Error(`Server error ${res.status}`);
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
        throw new Error(err.detail || err.message || `Request failed: ${res.status}`);
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
  rulePack?: string
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

const SHARE_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace("/api/v1", "") ||
  "http://localhost:8000";

export async function fetchSharedAnalysis(
  shortId: string
): Promise<SharedAnalysis> {
  // Public endpoint — no auth needed, but still benefits from error handling
  const res = await fetch(`${SHARE_BASE}/s/${shortId}`);
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
