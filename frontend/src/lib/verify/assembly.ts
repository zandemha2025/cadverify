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
  num_boundary_faces: number | null;
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

// ── P3b: the REAL per-part analysis shapes (mirror of the backend
// assembly_analysis_service payload — see analyze_assembly_sync). Every field
// is rendered VERBATIM from the engine; nothing here is fabricated. ──────────

/** A single should-cost estimate row (the engine's report_to_dict headline). */
export interface PartEstimate {
  process: string | null;
  material: string | null;
  quantity: number | null;
  unit_cost_usd: number | null;
  fixed_cost_usd: number | null;
  variable_cost_usd: number | null;
  est_error_band_pct: number | null;
  dfm_verdict: string | null;
  /** The engine's lead-time band object (days), NOT a string. */
  lead_time: { low_days: number; high_days: number; mid_days?: number } | null;
}

/** The compact DFM view for a part — the SAME AnalysisResult /validate serializes. */
export interface PartDfmSummary {
  verdict: string;
  best_process: string | null;
  issue_count: number;
  top_issues: Array<{ code: string; severity: string; message: string }>;
}

/** The COTS / standard-hardware block for a part (bolt/nut/screw/…). When present
 *  the part is BUY, not make: the answer is the catalog BUY price. No in-house
 *  machined fab figure is emitted for it (an aluminium/sheet-metal cost for a steel
 *  fastener mis-models the physics). Mirrors the engine's `classify_cots_fastener`
 *  output VERBATIM — the buy-price is a labelled DEFAULT catalog estimate, never a
 *  live quote; `nominal_size` is an APPROXIMATE geometry-inferred size, never a
 *  verified thread spec. */
/** Layer A part identity — a genuine, catalog-checkable standard-fastener ID that
 *  UPGRADES the approximate `nominal_size`. Present only when the fastener's REAL
 *  across-flats (measured from the mesh, not the bbox) cleanly matches the ISO/DIN
 *  standards catalog with confidence. Mirrors the engine's
 *  `identify_standard_fastener` output VERBATIM. Honest by construction: the
 *  across-flats is MEASURED and the size is CATALOG (ISO 4032 / 4014 / 4762); the
 *  pitch is ASSUMED coarse, and grade/material/SKU are never claimed (see `caveats`). */
export interface PartCotsIdentity {
  /** The ISO standard the envelope conforms to, e.g. "ISO 4032". */
  standard_id: string;
  /** Human designation, e.g. "M12 hex nut (ISO 4032 / DIN 934)". */
  designation: string;
  /** Nominal thread, e.g. "M12". */
  nominal: string;
  /** Thread spec with the assumption flagged, e.g. "M12 × 1.75 (coarse, assumed)". */
  thread: string;
  /** REAL across-flats measured from the mesh (mm). */
  across_flats_mm_measured: number;
  /** The matched standard's nominal across-flats (mm). */
  across_flats_mm_standard: number;
  /** |measured − standard| (mm). */
  residual_mm: number;
  across_corners_mm_measured?: number;
  ac_af_ratio?: number;
  /** True only when the cross-section is a clean hexagon (ratio ~1.155). */
  hex_confirmed: boolean;
  confidence: "high" | "medium" | "low" | string;
  /** e.g. "MEASURED (across-flats, axis via bore_cylinder) + CATALOG (ISO 4032)". */
  provenance: string;
  measured_dimension?: string;
  axis_source?: string;
  /** Explicit honesty notes (pitch assumed, grade not determinable, envelope not SKU). */
  caveats: string[];
}

export interface PartCots {
  is_cots: boolean;
  kind: string;
  confidence: string;
  detected_by: string;
  recommendation: string;
  buy_price_usd: number;
  buy_price_range_usd: [number, number];
  buy_price_provenance: string;
  note: string;
  /** Approximate nominal size inferred from the bounding box, e.g. "≈M8 × 30mm"
   *  (bolt) / "≈M8 nut". Labelled approximate — NOT a verified thread spec. */
  nominal_size?: string;
  nominal_size_note?: string;
  /** Layer A identity: the catalog-checkable upgrade over `nominal_size`, present
   *  only when the measured across-flats confidently matches a standard. When absent,
   *  the approximate `nominal_size` is the best available and is rendered unchanged. */
  identity?: PartCotsIdentity;
}

/** The should-cost block for a part (or an honest engine refusal). */
export interface PartShouldCost {
  status: string;
  reason?: string;
  cost_quantity?: number;
  make_now_process?: string | null;
  make_now_material?: string | null;
  crossover_qty?: number | null;
  /** The engine's decision object, keyed by quantity — NOT a string. */
  recommendation?: Record<string, unknown> | null;
  estimates?: PartEstimate[];
  /** Present ONLY for a COTS part: `cost_basis = "not_modeled_for_cots"` — the
   *  in-house machined fab figure is intentionally NOT emitted (it would mis-model
   *  fastener physics); the BUY price in `cots` is the answer. */
  cost_basis?: string;
  cost_basis_note?: string;
}

/** One analyzed part: quantity is a FACT (tree count); dfm/should-cost from the
 *  single-part engine; `error` is an HONEST per-part failure (never a fake number). */
export interface PartAnalysis {
  id: string;
  name: string;
  tree_path: string;
  quantity: number;
  world_volume_mm3: number;
  bbox_size_mm: [number, number, number];
  dfm_summary?: PartDfmSummary;
  should_cost?: PartShouldCost;
  /** Standard off-the-shelf hardware (BUY, not make) when the engine flagged it. */
  cots?: PartCots;
  error?: { code: string; message: string };
}

/** A real geometric contact/interference pair — a SIGNAL, not a fault verdict. */
export interface InterferencePair {
  part_a: { id: string; name: string; tree_path: string };
  part_b: { id: string; name: string; tree_path: string };
  type: "interpenetration" | "contact";
  penetration_vertices: number;
  min_gap_mm: number | null;
  note: string;
}

export interface InterferenceBlock {
  method: string;
  contact_tolerance_mm: number;
  meshed_parts: number;
  candidate_pairs: number;
  pairs_checked: number;
  pairs_capped: boolean;
  pairs_cap: number;
  deadline_reached: boolean;
  pairs: InterferencePair[];
}

export interface AssemblyAnalysis {
  per_part: PartAnalysis[];
  not_analyzed: Array<{ id: string; name: string; tree_path: string; reason: string }>;
  quantities_by_design: Record<string, number>;
  interference: InterferenceBlock;
  cost_context: {
    material_class: string;
    region: string;
    assemblies_per_year: number | null;
    quantity_basis: string;
  };
  analysis_summary: {
    parts_total: number;
    parts_analyzed: number;
    parts_ok: number;
    parts_errored: number;
    parts_not_analyzed: number;
    parts_capped: boolean;
    analyze_cap: number;
    interference_pairs: number;
    elapsed_sec: number;
  };
  boundaries: Record<string, string>;
}

export type AssemblyProbe =
  | { kind: "not_candidate" }
  | { kind: "single_part" }
  | { kind: "assembly"; render: AssemblyRender }
  | { kind: "refused"; title: string; action: string };

async function postAssembly(file: File, format: "json" | "glb" | "analysis"): Promise<Response | null> {
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

async function refusalFromResponse(response: Response, fallback: string): Promise<AssemblyProbe> {
  let detail = "";
  try {
    const body = (await response.json()) as { detail?: unknown };
    detail = typeof body.detail === "string" ? body.detail : "";
  } catch {
    // A non-JSON error is still a refusal. Never reinterpret it as a single part.
  }
  return {
    kind: "refused",
    title: "This assembly could not be opened",
    action: detail || fallback,
  };
}

/**
 * Probe a STEP/IGES upload without silently downgrading a failed assembly request
 * into the single-part pipeline. Only the backend's explicit `single_part`
 * classification may take that fallback. Every transport, parse, and GLB failure
 * becomes a visible refusal with a retry/export action.
 */
export async function probeAssembly(
  file: File,
  post: (file: File, format: "json" | "glb" | "analysis") => Promise<Response | null> = postAssembly,
): Promise<AssemblyProbe> {
  if (!isAssemblyCandidate(file.name)) return { kind: "not_candidate" };

  const jsonRes = await post(file, "json");
  if (!jsonRes) {
    return {
      kind: "refused",
      title: "Assembly check could not reach the server",
      action: "Check the connection and retry. The file was not analyzed as a single part.",
    };
  }
  if (!jsonRes.ok) {
    return refusalFromResponse(
      jsonRes,
      "Export the assembly as STEP AP242 or IGES, then retry.",
    );
  }

  let model: AssemblyModel;
  try {
    model = (await jsonRes.json()) as AssemblyModel;
  } catch {
    return {
      kind: "refused",
      title: "Assembly response was unreadable",
      action: "Retry the upload. The file was not analyzed as a single part.",
    };
  }
  if (model.kind === "single_part" && model.part_count === 1) {
    return { kind: "single_part" };
  }
  if (model.kind !== "assembly" || model.part_count < 2) {
    return {
      kind: "refused",
      title: "Assembly structure was not confirmed",
      action: "Export the assembly as STEP AP242 or IGES, then retry.",
    };
  }

  const glbRes = await post(file, "glb");
  if (!glbRes) {
    return {
      kind: "refused",
      title: "Assembly preview could not reach the server",
      action: "Check the connection and retry. No single-part verdict was substituted.",
    };
  }
  if (!glbRes.ok) {
    return refusalFromResponse(
      glbRes,
      "The measured assembly was kept, but its preview could not be built. Retry the upload.",
    );
  }
  let blob: Blob;
  try {
    blob = await glbRes.blob();
  } catch {
    return {
      kind: "refused",
      title: "Assembly preview was unreadable",
      action: "Retry the upload. No single-part verdict was substituted.",
    };
  }
  if (!blob.size) {
    return {
      kind: "refused",
      title: "Assembly preview was empty",
      action: "Retry the upload or export the assembly as STEP AP242.",
    };
  }

  const glbUrl = URL.createObjectURL(blob);
  return {
    kind: "assembly",
    render: {
      model,
      glbUrl,
      revoke: () => URL.revokeObjectURL(glbUrl),
    },
  };
}

/** Compatibility helper for callers that only need a confirmed assembly. */
export async function fetchAssembly(file: File): Promise<AssemblyRender | null> {
  const outcome = await probeAssembly(file);
  return outcome.kind === "assembly" ? outcome.render : null;
}

/**
 * Fetch the REAL P3 per-part analysis for an assembly (`format=analysis`): per-
 * part DFM verdict + should-cost from the SAME single-part engine, real per-part
 * quantity from the product tree, and real geometric interference. This is the
 * heavier call (~15s on AS1 — the per-part cost engine runs on every solid), so
 * it is fetched SEPARATELY from the fast json+glb render (`fetchAssembly`): the
 * stage + tree appear immediately, then the analysis merges in when it lands.
 *
 * The response is a SUPERSET of `format=json` (the model plus an `analysis`
 * block); we only need the `analysis` here since the model already rendered.
 * Returns null on any failure so the panel shows an honest "analysis
 * unavailable" state and NEVER fabricates a verdict/cost.
 */
export async function fetchAssemblyAnalysis(file: File): Promise<AssemblyAnalysis | null> {
  if (!isAssemblyCandidate(file.name)) return null;
  const res = await postAssembly(file, "analysis");
  if (!res || !res.ok) return null;
  try {
    const body = (await res.json()) as { analysis?: AssemblyAnalysis };
    return body.analysis ?? null;
  } catch {
    return null;
  }
}
