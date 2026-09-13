import { API_BASE } from "@/lib/api-base";

export interface FitResult {
  coordinate_frame: "shared_source_frame";
  seating: { method: string; accepted: boolean; reason: string; transform: number[][]; manual_nudge_mm: number[] };
  collision: { intersects: boolean; volume_mm3: number; method: string; region: null | { region_center: [number, number, number]; part_a_faces: number[]; part_b_faces: number[]; render_geometry: { available: boolean; media_type?: string; encoding?: string; data?: string; reason?: string } } };
  clearance: { closest_sampled_gap_mm: number; method: string; tight_zone: { region_center: [number, number, number] | null; part_a_faces: number[]; part_b_faces: number[]; sample_count: number } };
  timing_ms: { collision_boolean: number; sampled_clearance: number; pair_total: number };
  limits: string[];
}

export async function measureContextFit(part: File, context: File, seating: "shared_frame" | "auto", nudge: [number, number, number]): Promise<FitResult> {
  const form = new FormData();
  form.append("part_a", part);
  form.append("part_b", context);
  const query = new URLSearchParams({ seating, nudge_x_mm: String(nudge[0]), nudge_y_mm: String(nudge[1]), nudge_z_mm: String(nudge[2]) });
  const response = await fetch(`${API_BASE}/validate/fit?${query}`, { method: "POST", body: form });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body?.detail ?? body;
    const message = detail?.message || body?.message || (typeof detail === "string" ? detail : "Fit check failed");
    const nextAction = detail?.next_action;
    throw new Error(nextAction ? `${message} ${nextAction}` : message);
  }
  return response.json() as Promise<FitResult>;
}
