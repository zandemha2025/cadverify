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
  processes?: string[]
): Promise<ValidationResult> {
  const formData = new FormData();
  formData.append("file", file);

  let url = `${API_BASE}/validate`;
  if (processes && processes.length > 0) {
    url += `?processes=${processes.join(",")}`;
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
