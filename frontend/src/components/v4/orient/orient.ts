/**
 * Which way the part sits for a check, as the part page shows it.
 *
 * The engine reads the part's +Z as up: the build direction for printing
 * (faces past a process's overhang limit need support) and the direction the
 * tool opens for molding and casting (walls parallel to it need draft; what
 * blocks it is an undercut). An orientation is a rotation R from the file's
 * coordinates to the placed part (row-major, 9 numbers; its third row is the
 * file direction that points up). The backend (src/analysis/orientation.py)
 * applies the same R before a check and records it on the result.
 *
 * Pure: no React, no fetch, and only relative `.ts` runtime imports, so it runs
 * under `node --test` (orient.test.ts). Numbers shown to people come from the
 * engine (the check, or GET /parts/{hash}/orientations); the shading helper here
 * only colours the 3D view with the check's own rule.
 */
import type { CostReport, ValidationResult } from "@/lib/api";
import type { OwnedMachine } from "@/lib/verify/machine-api";
import { buildMethods, priceAt, trimNum, VERDICT_LABEL, type Method } from "../part/model.ts";
import { processLabel, processName } from "../process-names.ts";

export type Mat = number[];
export type Vec = [number, number, number];

export const IDENTITY: Mat = [1, 0, 0, 0, 1, 0, 0, 0, 1];

/* ── rotations ──────────────────────────────────────────────────────────── */

export function mul(a: Mat, b: Mat): Mat {
  const out = new Array<number>(9).fill(0);
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) for (let k = 0; k < 3; k++) out[i * 3 + j] += a[i * 3 + k] * b[k * 3 + j];
  return snap(out);
}

/** Entries within 1e-9 of 0 or ±1 become exactly that (90° steps stay exact; no -0). */
export function snap(m: Mat): Mat {
  return m.map((v) => {
    const r = Math.round(v);
    const x = Math.abs(v - r) < 1e-9 && Math.abs(r) <= 1 ? r : v;
    return x === 0 ? 0 : x;
  });
}

/** A quarter turn about a placed axis (right-handed, looking down the axis). */
export function quarter(axis: "x" | "y" | "z", sign: 1 | -1): Mat {
  const s = sign;
  if (axis === "x") return [1, 0, 0, 0, 0, -s, 0, s, 0];
  if (axis === "y") return [0, 0, s, 0, 1, 0, -s, 0, 0];
  return [0, -s, 0, s, 0, 0, 0, 0, 1];
}

/** R turned a further quarter about the placed axis. */
export function turned(r: Mat, axis: "x" | "y" | "z", sign: 1 | -1 = 1): Mat {
  return mul(quarter(axis, sign), r);
}

export function isIdentity(r: Mat | null | undefined): boolean {
  return !r || r.every((v, i) => Math.abs(v - IDENTITY[i]) < 1e-9);
}

export function exact(r: Mat): boolean {
  return r.every((v) => v === 0 || v === 1 || v === -1);
}

export function upOf(r: Mat): Vec {
  return [r[6], r[7], r[8]];
}

export function same(a: Mat | null | undefined, b: Mat | null | undefined, tol = 1e-6): boolean {
  const x = a ?? IDENTITY;
  const y = b ?? IDENTITY;
  return x.every((v, i) => Math.abs(v - y[i]) < tol);
}

function unit(v: readonly number[]): Vec | null {
  const n = Math.hypot(v[0], v[1], v[2]);
  if (!Number.isFinite(n) || n < 1e-12) return null;
  const u: Vec = [v[0] / n, v[1] / n, v[2] / n];
  const k = [0, 1, 2].reduce((a, b) => (Math.abs(u[b]) > Math.abs(u[a]) ? b : a), 0);
  if (Math.abs(Math.abs(u[k]) - 1) < 1e-9) {
    const e: Vec = [0, 0, 0];
    e[k] = Math.sign(u[k]);
    return e;
  }
  return u;
}

/**
 * The smallest rotation that puts the file direction `d` straight down, as the
 * backend's rotation_down: -Z stays, +Z turns 180° about X, ±X and ±Y a quarter turn.
 */
export function downTo(d: readonly number[]): Mat | null {
  const u = unit(d);
  if (!u) return null;
  const c = -u[2];
  if (c > 1 - 1e-15) return [...IDENTITY];
  if (c < -1 + 1e-15) return [1, 0, 0, 0, -1, 0, 0, 0, -1];
  if (u[2] === 0 && (u[0] === 0 || u[1] === 0)) {
    if (u[0]) return quarter("y", u[0] > 0 ? 1 : -1);
    return quarter("x", u[1] > 0 ? -1 : 1);
  }
  // Rodrigues about u × (0,0,-1).
  const v = [-u[1], u[0], 0];
  const s = Math.hypot(v[0], v[1], v[2]);
  const k = [v[0] / s, v[1] / s, v[2] / s];
  const K = [0, -k[2], k[1], k[2], 0, -k[0], -k[1], k[0], 0];
  const KK = mul(K, K);
  return snap(IDENTITY.map((id, i) => id + s * K[i] + (1 - c) * KK[i]));
}

/** The request value for POST /validate and /validate/cost, or null for the file's own. */
export function orientationParam(r: Mat | null | undefined): string | null {
  if (!r || isIdentity(r)) return null;
  return "rotation:" + r.map((v) => (v === 0 ? "0" : String(Number(v.toPrecision(15))))).join(",");
}

/** R from an orientation param ("rotation:…"), for re-checks that keep the shown orientation. */
export function fromParam(p: string | null | undefined): Mat {
  if (!p || !p.startsWith("rotation:")) return [...IDENTITY];
  const n = p.slice(9).split(",").map(Number);
  return n.length === 9 && n.every(Number.isFinite) ? snap(n) : [...IDENTITY];
}

const AXIS = ["X", "Y", "Z"];

function axisName(v: Vec): string | null {
  const k = [0, 1, 2].reduce((a, b) => (Math.abs(v[b]) > Math.abs(v[a]) ? b : a), 0);
  if (Math.abs(Math.abs(v[k]) - 1) > 1e-9) return null;
  return `${v[k] > 0 ? "+" : "−"}${AXIS[k]}`;
}

/** "As in the file", "File +Y up", or the tilted direction. Matches the backend's label. */
export function label(r: Mat | null | undefined): string {
  if (!r || isIdentity(r)) return "As in the file";
  const up = upOf(r);
  const name = axisName(up);
  return name ? `File ${name} up` : `Tilted: file direction (${up.map((c) => c.toFixed(2).replace("-0.00", "0.00")).join(", ")}) up`;
}

/* ── what the record says ───────────────────────────────────────────────── */

export interface OrientationRecord {
  rotation: number[][];
  up_in_file: number[];
  label: string;
  exact: boolean;
  key: string;
  note?: string;
  file_face_hash?: string;
}

/** The orientation a check or saved record used; null means the file's own. */
export function recordOf(x: ValidationResult | CostReport | null | undefined): OrientationRecord | null {
  const o = (x as { orientation?: OrientationRecord } | null | undefined)?.orientation;
  return o && Array.isArray(o.rotation) && o.rotation.length === 3 ? o : null;
}

export function matOf(rec: OrientationRecord | null | undefined): Mat {
  if (!rec) return [...IDENTITY];
  const flat = rec.rotation.flat().map(Number);
  return flat.length === 9 && flat.every(Number.isFinite) ? snap(flat) : [...IDENTITY];
}

/* ── the rules, per process ─────────────────────────────────────────────── */

export interface Rules {
  [process: string]: { overhang_deg?: number; draft_deg?: number };
}

/**
 * bridges: for FDM, where flat spans between walls print as bridges in a way
 * (candidate rotation, and boxes [x0, y0, z0, x1, y1, z1] as fractions of the
 * placed part's box, from the engine); those faces aren't coloured.
 */
export type Shade = { kind: "overhang" | "draft"; deg: number; bridges?: { r: Mat; boxes: number[][] }[] };

const POWDER = new Set(["sls", "mjf", "binder_jetting"]);
const OWN_AXIS = new Set(["cnc_turning", "wire_edm", "sheet_metal", "investment_casting"]);
const SETUPS = new Set(["cnc_3axis", "cnc_5axis"]);

export function shadeFor(process: string | null | undefined, rules: Rules | null | undefined): Shade | null {
  const r = process && rules ? rules[process] : null;
  if (r?.overhang_deg != null) return { kind: "overhang", deg: r.overhang_deg };
  if (r?.draft_deg != null) return { kind: "draft", deg: r.draft_deg };
  return null;
}

/** One line: why the orientation matters (or doesn't) for this process, in the check's own terms. */
export function whyLine(process: string | null | undefined, rules: Rules | null | undefined): string {
  if (!process) return "The check reads the part's +Z as up: the build direction for printing, and the direction the tool opens for molding and casting.";
  const name = processName(process);
  const r = rules?.[process];
  if (r?.overhang_deg != null) {
    const extra = process === "sla" ? "; large downward areas also pull on the resin tank" : process === "dmls" || process === "slm" ? "; large flat areas on the plate can curl" : "";
    return `${name} builds the part up from the plate: faces that overhang more than ${trimNum(r.overhang_deg, 0)}° need support${extra}.`;
  }
  if (r?.draft_deg != null) {
    return `${name} opens the tool along the part's up direction: walls parallel to it need ${trimNum(r.draft_deg, 0)}° of draft, and anything that blocks the opening is an undercut.`;
  }
  if (POWDER.has(process)) return `${name} needs no support: the powder holds the part, so orientation only changes height and nesting, and the price already uses the best fit.`;
  if (SETUPS.has(process)) return `${name}: the machinist plans the setups, so turning the file changes only which faces are marked as facing away from the tool.`;
  if (OWN_AXIS.has(process)) return `${name}: the check works from the part's own axis or blank, so turning the file changes nothing here.`;
  return `${name}: this check doesn't read the orientation.`;
}

/* ── shading the 3D view with the check's own rule ──────────────────────── */

/**
 * Triangles the check's rule marks in orientation R, from non-indexed positions
 * (9 floats a triangle, file coordinates): overhang past `deg` (except faces
 * resting on the plate), or side walls (80–100° from up) with less draft than
 * `deg`. The same rule as check_overhangs / check_draft_angles; used only to
 * colour the view; the figures shown come from the engine.
 */
export function shadeFaces(pos: ArrayLike<number>, r: Mat, shade: Shade): number[] {
  const n = Math.floor(pos.length / 9);
  const up = upOf(r);
  const angles = new Float64Array(n);
  const z = new Float64Array(n);
  const lo = [Infinity, Infinity, Infinity];
  const hi = [-Infinity, -Infinity, -Infinity];
  for (let f = 0; f < n; f++) {
    const o = f * 9;
    const ax = pos[o], ay = pos[o + 1], az = pos[o + 2];
    const bx = pos[o + 3], by = pos[o + 4], bz = pos[o + 5];
    const cx = pos[o + 6], cy = pos[o + 7], cz = pos[o + 8];
    const ux = bx - ax, uy = by - ay, uz = bz - az;
    const vx = cx - ax, vy = cy - ay, vz = cz - az;
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const len = Math.hypot(nx, ny, nz);
    const cos = len > 0 ? (nx * up[0] + ny * up[1] + nz * up[2]) / len : 0;
    angles[f] = (Math.acos(Math.max(-1, Math.min(1, cos))) * 180) / Math.PI;
    z[f] = (up[0] * (ax + bx + cx) + up[1] * (ay + by + cy) + up[2] * (az + bz + cz)) / 3;
    for (let k = 0; k < 3; k++) {
      for (let p = 0; p < 3; p++) {
        const v = r[k * 3] * pos[o + p * 3] + r[k * 3 + 1] * pos[o + p * 3 + 1] + r[k * 3 + 2] * pos[o + p * 3 + 2];
        if (v < lo[k]) lo[k] = v;
        if (v > hi[k]) hi[k] = v;
      }
    }
  }
  const out: number[] = [];
  if (shade.kind === "overhang") {
    let zmin = Infinity;
    for (let f = 0; f < n; f++) if (z[f] < zmin) zmin = z[f];
    const diag = n ? Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) : 0;
    const tol = Math.max(0.1, diag * 1e-3);
    // Bridged spans, from the engine's way with the same face down (a spin on the plate keeps them):
    // face centres in that way's placed box, as fractions, inside one of its boxes.
    const upR = upOf(r);
    const way = shade.bridges?.find((b) => b.boxes.length && upOf(b.r).every((v, k) => Math.abs(v - upR[k]) < 1e-6)) ?? null;
    const at = (m: Mat, o: number, k: number) => m[k * 3] * pos[o] + m[k * 3 + 1] * pos[o + 1] + m[k * 3 + 2] * pos[o + 2];
    const wlo = [Infinity, Infinity, Infinity];
    const whi = [-Infinity, -Infinity, -Infinity];
    if (way) {
      for (let o = 0; o + 2 < n * 9; o += 3) {
        for (let k = 0; k < 3; k++) {
          const v = at(way.r, o, k);
          if (v < wlo[k]) wlo[k] = v;
          if (v > whi[k]) whi[k] = v;
        }
      }
    }
    const bridged = (f: number) => {
      if (!way) return false;
      const o = f * 9;
      const c = [0, 1, 2].map((k) => {
        const v = (at(way.r, o, k) + at(way.r, o + 3, k) + at(way.r, o + 6, k)) / 3;
        const span = whi[k] - wlo[k];
        return span > 0 ? (v - wlo[k]) / span : 0;
      });
      const eps = 2e-3;
      return way.boxes.some((b) => c.every((v, k) => v >= b[k] - eps && v <= b[k + 3] + eps));
    };
    for (let f = 0; f < n; f++) {
      const onPlate = z[f] <= zmin + tol && angles[f] >= 175;
      if (angles[f] > 90 + shade.deg && !onPlate && !bridged(f)) out.push(f);
    }
  } else {
    for (let f = 0; f < n; f++) if (angles[f] > 80 && angles[f] < 100 && Math.abs(90 - angles[f]) < shade.deg) out.push(f);
  }
  return out;
}

/* ── ways to lay it down (GET /parts/{hash}/orientations) ───────────────── */

export interface Candidate {
  id: string;
  basis: "side" | "flat_face" | "picked";
  rotation: number[][];
  orientation: string | null;
  label: string;
  up_in_file: number[];
  down_in_file: number[];
  exact: boolean;
  height_mm: number;
  footprint_mm: [number, number];
  on_plate_area_mm2: number;
  /**
   * volume_cm3: the space under those faces down to the part or plate (an estimate).
   * FDM only: flat spans between walls that print as bridges (not counted above).
   */
  support: Record<string, { faces: number; area_mm2: number; volume_cm3?: number; bridges?: number; bridged_area_mm2?: number; longest_bridge_mm?: number; bridge_boxes?: number[][] }>;
  draft: Record<string, { faces: number; area_mm2: number }>;
  downward_area_mm2: number;
  downward_share_pct: number | null;
  face_area_mm2?: number;
  /** Layers at a typical layer per process (layer_mm). */
  layers?: Record<string, number>;
  /** Fits the work area the check uses, standing this way (any turn on the plate). */
  fits?: Record<string, boolean>;
  /** The findings that read the build direction this way would raise, per process. */
  flags?: Record<string, string[]>;
}

export interface Options {
  mesh_hash: string;
  faces: number;
  analysed_faces: number;
  decimated: boolean;
  surface_area_mm2: number;
  rules: Rules;
  candidates: Candidate[];
  best: Record<string, string>;
  ranking: { printing: string; molding: string };
  limits: string[];
  work_areas_mm?: Record<string, number[]>;
  layer_mm?: Record<string, number>;
}

/** Said wherever orientations are compared: the cost model doesn't price these yet. */
export const PRICES_LINE = "Prices don't yet include support material or print height, so they're the same in every orientation.";

const FLAG_WORDS: Record<string, string> = {
  OVERHANG: "needs support",
  CUPPING_RISK: "cupping risk in the resin tank",
  RESIDUAL_STRESS_RISK: "curl risk on large flat areas",
  INSUFFICIENT_DRAFT: "walls without draft",
};

/** "needs support, cupping risk in the resin tank" for this way and process; "" when none. */
export function flagWords(c: Candidate, process: string | null): string {
  const codes = process ? c.flags?.[process] ?? [] : [];
  return codes.map((k) => FLAG_WORDS[k] ?? k).join(", ");
}

/** "225 layers at 0.2 mm" for this way and process, when the engine counted them. */
export function layerWords(c: Candidate, process: string | null, options: Options | null): string | null {
  const n = process ? c.layers?.[process] : undefined;
  const t = process ? options?.layer_mm?.[process] : undefined;
  return n != null && t != null ? `${n.toLocaleString("en-US")} layers at ${trimNum(t, 2)} mm` : null;
}

/** "fits the 300 × 300 × 350 mm work area" or "doesn't fit … standing this way". */
export function fitWords(c: Candidate, process: string | null, options: Options | null): string | null {
  const fit = process ? c.fits?.[process] : undefined;
  const env = process ? options?.work_areas_mm?.[process] : undefined;
  if (fit == null || !env) return null;
  const area = `${env.map((d) => trimNum(d, 0)).join(" × ")} mm work area`;
  return fit ? `fits the ${area}` : `doesn't fit the ${area} standing this way`;
}

export function candidateMat(c: Candidate): Mat {
  return snap(c.rotation.flat().map(Number));
}

/** The compared way with the same up direction as R (support, draft and height depend only on it). */
export function candidateFor(options: Options | null, r: Mat): Candidate | null {
  if (!options) return null;
  const up = upOf(r);
  return options.candidates.find((c) => Math.abs(c.up_in_file[0] - up[0]) + Math.abs(c.up_in_file[1] - up[1]) + Math.abs(c.up_in_file[2] - up[2]) < 1e-6) ?? null;
}

function mm(v: number): string {
  return `${trimNum(v, v >= 100 ? 0 : 1)} mm`;
}

function area(v: number): string {
  return `${Math.round(v).toLocaleString("en-US")} mm²`;
}

/** The ways ranked for this process (best first), with the facts that decide it. */
export function rankedFor(options: Options | null, process: string | null): Candidate[] {
  if (!options) return [];
  const list = [...options.candidates];
  const order = new Map(list.map((c, i) => [c.id, i]));
  const r = process ? options.rules[process] : null;
  if (r?.overhang_deg != null && process) {
    list.sort((a, b) => a.support[process].area_mm2 - b.support[process].area_mm2 || a.height_mm - b.height_mm || b.on_plate_area_mm2 - a.on_plate_area_mm2 || order.get(a.id)! - order.get(b.id)!);
  } else if (r?.draft_deg != null && process) {
    list.sort((a, b) => a.draft[process].area_mm2 - b.draft[process].area_mm2 || order.get(a.id)! - order.get(b.id)!);
  }
  return list;
}

/** The physical facts of a way, for the selected process: support, then height, layers and fit. */
export function candidateFacts(c: Candidate, process: string | null, rules: Rules | null, options: Options | null = null): { main: string; sub: string } {
  const r = process && rules ? rules[process] : null;
  const shape = [`${mm(c.height_mm)} tall`, layerWords(c, process, options), `${trimNum(c.footprint_mm[0], 0)} × ${trimNum(c.footprint_mm[1], 0)} mm on the plate`, fitWords(c, process, options)].filter(Boolean).join(" · ");
  if (r?.overhang_deg != null && process) {
    const s = c.support[process];
    const vol = s.volume_cm3 != null && s.faces ? `, about ${trimNum(s.volume_cm3, s.volume_cm3 >= 10 ? 0 : 1)} cm³ under it (estimate)` : "";
    return { main: (s.faces ? `Support on ${area(s.area_mm2)}${vol}` : "No support needed") + bridgeWords(s), sub: shape };
  }
  if (r?.draft_deg != null && process) {
    const d = c.draft[process];
    return { main: d.faces ? `${area(d.area_mm2)} of wall without ${trimNum(r.draft_deg, 0)}° draft` : "Every wall has its draft", sub: `Tool opens along the file's ${axisWord(c.up_in_file)}` };
  }
  return { main: shape, sub: "" };
}

/** "; a flat span bridges 20 mm" / "; 3 flat spans bridge, up to 60 mm" (FDM), or "". */
export function bridgeWords(s: { bridges?: number; longest_bridge_mm?: number } | undefined): string {
  const n = s?.bridges ?? 0;
  if (!n) return "";
  const len = mm(s?.longest_bridge_mm ?? 0);
  return n === 1 ? `; a flat span bridges ${len}` : `; ${n} flat spans bridge, up to ${len}`;
}

/** The file direction that points up: "+Z", "−Y", or the tilted direction. */
export function upWord(r: Mat | null | undefined): string {
  const up = upOf(r ?? IDENTITY);
  return axisName(up) ?? `(${up.map((c) => c.toFixed(2).replace("-0.00", "0.00")).join(", ")})`;
}

function axisWord(v: number[]): string {
  return axisName([v[0], v[1], v[2]])?.replace(/^[+−]/, "") ?? "tilted axis";
}

/** A way in words: "On the file's −Y side", "On a flat face (2,400 mm²)", "On the face you picked". */
export function candidateName(c: Candidate): string {
  if (c.basis === "picked") return "On the face you picked";
  if (c.basis === "flat_face") return `On a flat face (${area(c.face_area_mm2 ?? 0)})`;
  if (c.id === "down-z") return "As in the file";
  const down = axisName([c.down_in_file[0], c.down_in_file[1], c.down_in_file[2]]);
  return down ? `On the file's ${down} side` : c.label;
}

/** How prices relate to the orientation, in the engine's own words (the first of its limits). */
export function priceBasis(options: Options | null): string | null {
  return options?.limits?.[0] ?? null;
}

/* ── before and after a re-check ────────────────────────────────────────── */

export interface Side {
  validation: ValidationResult | null;
  cost: CostReport | null;
  rotation: Mat;
}

export type Tone = "" | "ok" | "warn" | "bad";

export interface ChangeRow {
  what: string;
  before: string;
  now: string;
  tone: Tone;
}

export interface Comparison {
  rows: ChangeRow[];
  findings: { cleared: string[]; added: string[] };
  methods: { before: number; now: number; changed: { name: string; before: string; now: string; tone: Tone }[] };
  pricesSame: boolean;
  /** Methods whose price changed at some quantity (engine process codes). */
  pricesChanged: string[];
  process: string | null;
}

function scoreOf(v: ValidationResult | null, process: string) {
  return v?.process_scores?.find((p) => p.process === process) ?? null;
}

function canMake(methods: Method[]): number {
  return methods.filter((m) => m.verdict === "ok" || m.verdict === "warn").length;
}

function findingWords(code: string, process: string, v: ValidationResult | null): string {
  const i = scoreOf(v, process)?.issues.find((x) => x.code === code);
  return i?.message ?? code;
}

/** What changed between the check before and the re-check in another orientation, from the two results. */
export function compare(before: Side, now: Side, q: number, process: string | null, machines: OwnedMachine[] = [], options: Options | null = null): Comparison {
  const rows: ChangeRow[] = [];
  const hb = before.validation?.geometry?.bounding_box_mm?.[2];
  const hn = now.validation?.geometry?.bounding_box_mm?.[2];
  rows.push({ what: "Up (the file's axis)", before: upWord(before.rotation), now: upWord(now.rotation), tone: "" });
  if (hb != null && hn != null) rows.push({ what: "Height", before: mm(hb), now: mm(hn), tone: hn < hb ? "ok" : hn > hb ? "warn" : "" });
  const cb = candidateFor(options, before.rotation);
  const cn = candidateFor(options, now.rotation);
  const t = process ? options?.layer_mm?.[process] : undefined;
  if (process && t != null && cb?.layers?.[process] != null && cn?.layers?.[process] != null) {
    const lb = cb.layers[process];
    const ln = cn.layers[process];
    rows.push({ what: `Layers at ${trimNum(t, 2)} mm`, before: lb.toLocaleString("en-US"), now: ln.toLocaleString("en-US"), tone: ln < lb ? "ok" : ln > lb ? "warn" : "" });
  }
  if (process && cb?.fits?.[process] != null && cn?.fits?.[process] != null) {
    const w = (f: boolean) => (f ? "Fits" : "Doesn't fit");
    rows.push({ what: "Work area, standing this way", before: w(cb.fits[process]), now: w(cn.fits[process]), tone: cn.fits[process] && !cb.fits[process] ? "ok" : !cn.fits[process] && cb.fits[process] ? "bad" : "" });
  }
  const findings = { cleared: [] as string[], added: [] as string[] };
  if (process) {
    const b = scoreOf(before.validation, process);
    const n = scoreOf(now.validation, process);
    const bc = new Map((b?.issues ?? []).map((i) => [i.code, i]));
    const nc = new Map((n?.issues ?? []).map((i) => [i.code, i]));
    for (const [code] of bc) if (!nc.has(code)) findings.cleared.push(findingWords(code, process, before.validation));
    for (const [code] of nc) if (!bc.has(code)) findings.added.push(findingWords(code, process, now.validation));
    const support = (s: typeof b) => s?.issues.find((i) => i.code === "OVERHANG");
    const sb = support(b);
    const sn = support(n);
    if (sb || sn) {
      const words = (i: typeof sb) => (i ? `${(i.affected_face_count ?? i.affected_faces_sample?.length ?? 0).toLocaleString("en-US")} faces` : "None");
      rows.push({ what: "Faces needing support", before: words(sb), now: words(sn), tone: !sn ? "ok" : !sb ? "bad" : "" });
      const vb = cb?.support?.[process]?.volume_cm3;
      const vn = cn?.support?.[process]?.volume_cm3;
      if (vb != null && vn != null) {
        const v = (x: number) => (x ? `${trimNum(x, x >= 10 ? 0 : 1)} cm³` : "None");
        rows.push({ what: "Space under them (estimate)", before: v(vb), now: v(vn), tone: vn < vb ? "ok" : vn > vb ? "bad" : "" });
      }
    }
    const draft = (s: typeof b) => s?.issues.find((i) => i.code === "INSUFFICIENT_DRAFT");
    const db = draft(b);
    const dn = draft(n);
    if (db || dn) {
      const words = (i: typeof db) => (i ? `${(i.affected_face_count ?? 0).toLocaleString("en-US")} faces` : "None");
      rows.push({ what: "Walls without draft", before: words(db), now: words(dn), tone: !dn ? "ok" : !db ? "bad" : (dn.affected_face_count ?? 0) < (db.affected_face_count ?? 0) ? "ok" : "" });
    }
    const uc = (s: typeof b) => s?.issues.find((i) => i.code === "UNDERCUT_MOLDING");
    if (uc(b) || uc(n)) {
      const words = (i: ReturnType<typeof uc>) => (i ? `${(i.affected_face_count ?? 0).toLocaleString("en-US")} faces` : "None");
      rows.push({ what: "Undercut faces", before: words(uc(b)), now: words(uc(n)), tone: !uc(n) ? "ok" : !uc(b) ? "bad" : "" });
    }
    if (b && n && b.verdict !== n.verdict) rows.push({ what: `${processName(process)} check`, before: b.verdict, now: n.verdict, tone: n.verdict === "pass" ? "ok" : n.verdict === "fail" ? "bad" : "" });
  }
  const mb = buildMethods({ validation: before.validation, cost: before.cost, machines });
  const mn = buildMethods({ validation: now.validation, cost: now.cost, machines });
  const changed: Comparison["methods"]["changed"] = [];
  for (const m of mn) {
    const o = mb.find((x) => x.code === m.code);
    if (o && o.verdict !== m.verdict) {
      const good = (v: string) => v === "ok" || v === "warn";
      changed.push({ name: processLabel(m.code), before: VERDICT_LABEL[o.verdict], now: VERDICT_LABEL[m.verdict], tone: good(m.verdict) && !good(o.verdict) ? "ok" : !good(m.verdict) && good(o.verdict) ? "bad" : "" });
    }
  }
  const methods = { before: canMake(mb), now: canMake(mn), changed };
  rows.push({ what: "Methods that can make it", before: `${methods.before} of ${mb.length}`, now: `${methods.now} of ${mn.length}`, tone: methods.now > methods.before ? "ok" : methods.now < methods.before ? "bad" : "" });
  const pricesChanged: string[] = [];
  for (const m of mn) {
    const o = mb.find((x) => x.code === m.code);
    if (!o) continue;
    // Only quantities both checks priced (an earlier record may have priced other ones).
    if ([...m.prices.keys()].some((qq) => o.prices.has(qq) && priceAt(o, qq) !== priceAt(m, qq))) pricesChanged.push(m.code);
  }
  const pricesSame = pricesChanged.length === 0;
  void q;
  return { rows, findings, methods, pricesSame, pricesChanged, process };
}
