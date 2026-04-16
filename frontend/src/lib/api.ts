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

  const res = await fetch(url, { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Validation failed");
  }
  return res.json();
}

export async function validateQuick(file: File): Promise<{
  filename: string;
  verdict: string;
  geometry: Partial<GeometryInfo>;
  issues: Issue[];
}> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/validate/quick`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Quick validation failed");
  }
  return res.json();
}

export async function getProcesses(): Promise<{ processes: Array<{ process: string; material_count: number; machine_count: number; materials: string[]; machines: string[] }> }> {
  const res = await fetch(`${API_BASE}/processes`);
  return res.json();
}

export async function getMaterials(): Promise<{ materials: Material[] }> {
  const res = await fetch(`${API_BASE}/materials`);
  return res.json();
}

export async function getMachines(): Promise<{ machines: Machine[] }> {
  const res = await fetch(`${API_BASE}/machines`);
  return res.json();
}

export async function getRulePacks(): Promise<{ rule_packs: RulePackInfo[] }> {
  const res = await fetch(`${API_BASE}/rule-packs`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to fetch rule packs");
  }
  return res.json();
}

/* ------------------------------------------------------------------ */
/*  Analysis history types & client functions (Phase 3 — PERS-09)     */
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

export async function fetchAnalyses(params: {
  cursor?: string;
  limit?: number;
  verdict?: string;
}): Promise<AnalysesPage> {
  const url = new URL(`${API_BASE}/analyses`, window.location.origin);
  if (params.cursor) url.searchParams.set("cursor", params.cursor);
  if (params.limit) url.searchParams.set("limit", String(params.limit));
  if (params.verdict) url.searchParams.set("verdict", params.verdict);

  const res = await fetch(url.toString(), { headers: authHeaders() });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to fetch analyses");
  }
  const rateLimits = extractRateLimits(res.headers);
  const data = await res.json();
  return { ...data, rateLimits };
}

export async function fetchAnalysis(id: string): Promise<AnalysisDetail> {
  const res = await fetch(`${API_BASE}/analyses/${id}`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new Error(res.status === 404 ? "Analysis not found" : "Failed to fetch analysis");
  }
  return res.json();
}
