/**
 * Assembly client for the Verify stage.
 *
 * When an uploaded STEP/IGES file holds >= 2 solids it is an ASSEMBLY, not a
 * single part. The single-part path (STL parsed in-browser, or the decimated
 * per-part shell from /validate/preview-mesh) renders ONE shell. This client
 * talks to the assembly-aware backend sibling:
 *
 *   POST /validate/assembly?format=json → the structured AssemblyModel (parts +
 *        baked world positions + nested product tree + honest limits).
 *   POST /validate/assembly?format=glb  → ONE combined GLB with a named node per
 *        part (world transforms preserved) for the part-in-context render.
 *
 * Zero-egress, same-origin through the Next authed proxy (`/api/proxy/*` →
 * backend `/api/v1/*` with the httpOnly session cookie), exactly like
 * preview-mesh.ts. The GLB is a MESH-LEVEL shell (triangulated), NOT B-rep /
 * GD&T / PMI — it makes the assembly LOOK right, it asserts no analytic
 * semantics. A single-solid file classifies `single_part` and is left to the
 * existing single-part path untouched.
 *
 * NOTE: the proxy base is imported LAZILY (inside the fetch path) so the pure,
 * unit-tested helpers below carry no runtime module-alias dependency and load
 * under the repo's `node --test` TS-stripping runner.
 */

/** STEP/IGES suffixes the assembly endpoint accepts — only these are probed, so
 *  STL and everything else stay on the unchanged single-part path. */
const ASSEMBLY_SUFFIXES = [".step", ".stp", ".iges", ".igs"];

export function isAssemblyCandidate(fileName: string): boolean {
  const lower = fileName.toLowerCase();
  return ASSEMBLY_SUFFIXES.some((s) => lower.endsWith(s));
}

export interface WorldPose {
  bbox_min: [number, number, number];
  bbox_max: [number, number, number];
  bbox_size: [number, number, number];
  centroid: [number, number, number];
  volume: number;
}

export interface GeometrySummary {
  num_boundary_faces: number;
  num_triangles: number;
  num_vertices: number;
  bbox_dims: [number, number, number];
}

export interface PartInstance {
  id: string;
  name: string;
  occurrence: string;
  instance: number;
  tree_path: string;
  occ_label: string;
  world: WorldPose;
  geometry_summary: GeometrySummary;
  mesh_ref: string | null;
}

export interface TreeNode {
  name: string;
  occurrence: string;
  instance: number;
  part_id?: string;
  children?: TreeNode[];
}

export interface AssemblyModel {
  kind: "assembly" | "single_part";
  part_count: number;
  parts: PartInstance[];
  tree: TreeNode;
  assembly: {
    bbox_min: [number, number, number];
    bbox_max: [number, number, number];
    diagonal: number;
  };
  unique_designs: Record<string, number>;
  source_suffix: string;
  truncated?: boolean;
  skipped?: Array<Record<string, unknown>>;
  notes?: string[];
}

const FASTENER_HINTS = ["bolt", "nut", "screw", "washer", "rivet", "pin", "stud"];

/** Is this part a fastener by name/occurrence? Used only to bias the DEFAULT
 *  part-of-interest away from hardware — the user can still pick it. */
export function looksLikeFastener(part: PartInstance): boolean {
  const hay = `${part.name} ${part.occurrence}`.toLowerCase();
  return FASTENER_HINTS.some((h) => hay.includes(h));
}

/**
 * Choose a sensible default part-of-interest: the LARGEST non-fastener by
 * world volume. Falls back to the largest part overall if every part reads as
 * hardware, and to the first part if volumes are absent. Pure + deterministic
 * so it is unit-testable.
 */
export function defaultPartOfInterest(parts: PartInstance[]): string | null {
  if (parts.length === 0) return null;
  const byVolume = (a: PartInstance, b: PartInstance) =>
    (b.world?.volume ?? 0) - (a.world?.volume ?? 0);
  const nonFastener = parts.filter((p) => !looksLikeFastener(p)).sort(byVolume);
  if (nonFastener.length > 0 && (nonFastener[0].world?.volume ?? 0) > 0) {
    return nonFastener[0].id;
  }
  const largest = [...parts].sort(byVolume);
  return largest[0]?.id ?? parts[0].id;
}

export interface AssemblyRender {
  model: AssemblyModel;
  /** object URL for the combined GLB blob (caller revokes via `revoke`). */
  glbUrl: string;
  revoke: () => void;
}

async function postAssembly(file: File, format: "json" | "glb"): Promise<Response | null> {
  const { API_BASE } = await import("@/lib/api-base");
  const form = new FormData();
  form.append("file", file);
  try {
    return await fetch(`${API_BASE}/validate/assembly?format=${format}`, {
      method: "POST",
      body: form,
    });
  } catch {
    return null;
  }
}

/**
 * Detect + fetch. Returns the AssemblyModel + a renderable combined GLB when the
 * file is a real multi-part assembly; returns null for a single part, a
 * non-STEP/IGES file, or any failure (so the caller falls back to the UNCHANGED
 * single-part path — we never fabricate an assembly).
 */
export async function fetchAssembly(file: File): Promise<AssemblyRender | null> {
  if (!isAssemblyCandidate(file.name)) return null;

  const jsonRes = await postAssembly(file, "json");
  if (!jsonRes || !jsonRes.ok) return null;

  let model: AssemblyModel;
  try {
    model = (await jsonRes.json()) as AssemblyModel;
  } catch {
    return null;
  }
  // Single-solid files are NOT assemblies — leave them on the existing path.
  if (model.kind !== "assembly" || model.part_count < 2) return null;

  const glbRes = await postAssembly(file, "glb");
  if (!glbRes || !glbRes.ok) return null;
  let blob: Blob;
  try {
    blob = await glbRes.blob();
  } catch {
    return null;
  }
  if (!blob.size) return null;

  const glbUrl = URL.createObjectURL(blob);
  return {
    model,
    glbUrl,
    revoke: () => URL.revokeObjectURL(glbUrl),
  };
}
