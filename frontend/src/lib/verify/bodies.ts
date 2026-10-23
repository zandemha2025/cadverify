/**
 * A file that holds several bodies: what it holds, and each body checked as its own part.
 *
 *   The check's own result carries `part_type` (src/analysis/part_types.py): one
 *   solid, a solid with sealed voids, separate bodies, a weldment-like set of
 *   stock members, or an assembly; each body with its faces in the check's 3D
 *   view, its stock shape and the contacts between bodies.
 *
 *   POST /parts/{hash}/bodies         every body checked as its own part, from the
 *                                     kept file (no upload, no check used).
 *   POST /parts/{hash}/bodies/{n}/part body n as a part of its own: an STL copy
 *                                     ScaleCAD made, so checking it uses no check.
 *
 * Pure helpers on top; the proxy base is imported lazily so they run under
 * `node --test`.
 */
import { apiProblemDetail, apiRecoveryMessage } from "../api-recovery.ts";

export type PartKind =
  | "single_solid"
  | "single_solid_with_voids"
  | "separate_bodies"
  | "weldment"
  | "assembly"
  | "bodies"
  | "many_bodies"
  | "empty";

export interface BodyStock {
  kind: string;
  words: string;
  thickness_mm?: number;
  length_mm?: number;
  wall_mm?: number;
  od_mm?: number;
  section_mm?: number[];
  outline_mm?: number[];
  box_mm?: number[];
  ends?: "square" | "shaped";
}

export interface BodyInfo {
  id: number;
  label: string;
  name: string | null;
  /** Half-open [start, end) runs of the body's faces in the check's analysis mesh. */
  faces: [number, number][];
  faces_truncated?: boolean;
  face_count: number;
  closed: boolean;
  voids: number;
  volume_mm3: number;
  surface_area_mm2: number;
  bbox_mm: [number, number, number];
  centroid: [number, number, number];
  stock: BodyStock | null;
  shape: string;
  design: number;
  same_as: number | null;
  copies: number;
  tree_path?: string;
}

export interface BodyContact {
  a: number;
  b: number;
  type: "touching" | "near" | "overlap";
  gap_mm: number | null;
  overlap_mm: number | null;
  area_mm2: number;
  patch_mm: [number, number];
  outline_mm: number;
  ring: boolean;
  weld_like: boolean;
  /** The pair hit its work cap: a smaller sample than usual (or an overlap depth that is at least
   *  this), so its area and outline are rougher. */
  coarse?: boolean;
}

/** Close pairs of bodies whose contact wasn't checked (`of`: the close pairs in all), and why. */
export interface ContactsUnchecked {
  pairs: number;
  of: number;
  reasons: string[];
}

export interface PartType {
  version: number;
  kind: PartKind;
  body_count: number;
  shells?: number;
  all_closed?: boolean;
  bodies_share_edges?: boolean;
  summary: string;
  bodies?: BodyInfo[];
  designs?: number;
  contacts?: BodyContact[];
  contacts_complete?: boolean;
  /** Set when some close pairs weren't checked for contact; `contacts_note` says so in a sentence.
   *  The API adds the note to `summary` only when it found contacts (contactsNoteToShow). */
  contacts_unchecked?: ContactsUnchecked;
  contacts_note?: string;
  joints?: { count: number; weld_length_mm_estimate: number; words: string };
  route?: string[];
  source?: "mesh" | "step_product_tree";
  /** A STEP/IGES mesh whose touching solids merged: the body check reads its product tree instead. */
  provisional?: boolean;
  product_tree?: { source: string; parts: number; designs: Record<string, number> };
}

export interface BodyQuantityPrice {
  quantity_each: number;
  process: string | null;
  material: string | null;
  unit_cost_usd: number | null;
  per_file_usd: number | null;
  dfm_verdict: "pass" | "issues" | "fail" | null;
  lead_days: [number | null, number | null];
}

export interface BodyDesignCheck {
  design: number;
  bodies: number[];
  copies: number;
  status: "ok" | "geometry_invalid" | "error" | "not_checked" | "open";
  reason?: string | null;
  verdict?: "pass" | "issues" | "fail" | "unknown";
  dfm?: { verdict: string; best_process: string | null; issue_count: number; top_issues: { code: string; severity: string; message: string }[] };
  processes?: { can_make: number; of: number; verdicts: { process: string; verdict: string; score: number }[] };
  by_quantity?: Record<string, BodyQuantityPrice | null>;
  stock?: BodyStock | null;
  stock_material?: { material: string; mass_kg: number; usd: number; usd_per_kg: number; density_g_cm3: number; basis: string } | null;
  cut_blank?: Record<string, { unit_cost_usd: number; material: string | null }> | null;
  cots?: { is_cots?: boolean; kind?: string; buy_price_usd?: number; nominal_size?: string | null } | null;
  tooling_process?: string | null;
  crossover_qty?: number | null;
}

export interface BodiesCheck {
  filename: string;
  part_type: PartType;
  quantities: number[];
  material_class?: string;
  material_basis?: "request" | "default" | "weldment_default";
  designs: BodyDesignCheck[];
  total: { per_file_usd: Record<string, number | null>; basis: string; complete: boolean } | null;
  weldment?: {
    route: string[];
    members: number;
    material_usd: number | null;
    material_kg: number | null;
    material_complete: boolean;
    cut_blanks: number;
    cut_blanks_usd: Record<string, number | null> | null;
    joints: number | null;
    weld_length_mm_estimate: number | null;
    not_priced: string[];
    words: string;
  };
  assembly?: { words: string; pilot: boolean };
  checked?: { bodies: number; of: number; designs: number };
  checks_used: number;
  basis?: string;
  note?: string;
  source?: { mesh_hash: string; filename: string; product_tree_note?: string | null };
  elapsed_sec?: number;
}

export const MULTI_KINDS: ReadonlySet<PartKind> = new Set(["separate_bodies", "weldment", "assembly", "bodies"]);

/** A file of two or more bodies the check can read one by one. */
/**
 * The unchecked-contacts note to show beside the summary, or null: none to show, or
 * the summary already carries it (the API appends it when it found some contacts).
 */
export function contactsNoteToShow(pt: Pick<PartType, "summary" | "contacts_note"> | null | undefined): string | null {
  const note = pt?.contacts_note?.trim();
  if (!note) return null;
  return pt?.summary?.includes(note) ? null : note;
}

export function isMultiBody(pt: PartType | null | undefined): pt is PartType & { bodies: BodyInfo[] } {
  return !!pt && MULTI_KINDS.has(pt.kind) && (pt.bodies?.length ?? 0) > 1;
}

/** Several closed bodies, each a solid on its own (even when, as one mesh, the file isn't closed). */
export function closedBodies(pt: PartType | null | undefined): boolean {
  return isMultiBody(pt) && pt.all_closed === true;
}

/** Face indices from the body's runs, for the viewer's colouring. */
export function expandFaces(runs: readonly (readonly [number, number])[] | null | undefined, cap = 2_000_000): number[] {
  const out: number[] = [];
  for (const [s, e] of runs ?? []) {
    for (let f = s; f < e && out.length < cap; f += 1) out.push(f);
    if (out.length >= cap) break;
  }
  return out;
}

export class BodiesError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function checkBodies(
  key: string,
  opts: { materialClass?: string | null; qty?: number[] | null; owned?: string[] } = {},
): Promise<BodiesCheck> {
  const { API_BASE } = await import("@/lib/api-base");
  const q = new URLSearchParams();
  if (opts.materialClass) q.set("material_class", opts.materialClass);
  if (opts.qty?.length) q.set("qty", opts.qty.join(","));
  if (opts.owned?.length) q.set("owned_processes", opts.owned.join(","));
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/parts/${encodeURIComponent(key)}/bodies${q.toString() ? `?${q}` : ""}`, { method: "POST" });
  } catch {
    throw new BodiesError("Checking the bodies couldn’t reach the server. Try again.", 0);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 404) throw new BodiesError("This part’s file isn’t kept with the record, so its bodies can’t be checked here.", 404);
    throw new BodiesError(apiProblemDetail(body) ?? apiRecoveryMessage({ status: res.status, payload: body, resource: "body check" }), res.status);
  }
  return body as BodiesCheck;
}

export interface BodyPart {
  file: File;
  meshHash: string;
  filename: string;
  body: { id: number; of: number; name: string | null };
}

/** Body n as a file of its own, made by ScaleCAD and recorded as derived from this part. */
export async function bodyAsPart(key: string, bodyId: number): Promise<BodyPart> {
  const { API_BASE } = await import("@/lib/api-base");
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/parts/${encodeURIComponent(key)}/bodies/${bodyId}/part`, { method: "POST" });
  } catch {
    throw new BodiesError("Opening the body couldn’t reach the server. Try again.", 0);
  }
  const body = (await res.json().catch(() => null)) as { file_b64?: string; mesh_hash?: string; filename?: string; body?: BodyPart["body"] } | null;
  if (!res.ok || !body?.file_b64 || !body.filename) {
    throw new BodiesError(apiProblemDetail(body) ?? apiRecoveryMessage({ status: res.status, payload: body, resource: "body" }), res.status);
  }
  const raw = atob(body.file_b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return {
    file: new File([bytes], body.filename, { type: "model/stl" }),
    meshHash: body.mesh_hash ?? "",
    filename: body.filename,
    body: body.body ?? { id: bodyId, of: 0, name: null },
  };
}
