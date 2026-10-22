/**
 * Find and fix: every problem on a part, from the engine's own findings.
 *
 * A "problem" is one kind of finding (thin walls, missing draft, a sealed cavity…)
 * across every method that reported it, so the part shows it once and the sheet
 * lists what each method needs. The source is the check's ValidationResult; a saved
 * part with no stored analysis falls back to the cost record's blocker details (the
 * same serialized Issues, errors only). Every figure here is read from those
 * responses or parsed from the engine's own message; nothing is estimated.
 *
 * Pure: no React, no fetch, only relative `.ts` runtime imports (runs under node --test).
 */
import type { CostReport, Issue, ValidationResult } from "@/lib/api";
import { METHODS, issueKind, methodName, trimNum, type Kind } from "../part/model.ts";

/* ── families ──────────────────────────────────────────────────────────── */

interface FamilyDef {
  id: string;
  codes: string[];
  title: string;
  /** Where on the part it is, for "By place". */
  place: string;
  /** Nothing in the design changes: the shop sets it up, or another method makes it. */
  noChange?: "shop" | "method";
}

const FAMILIES: FamilyDef[] = [
  { id: "open", codes: ["NON_WATERTIGHT"], title: "The shell is open", place: "Open edges" },
  { id: "solid", codes: ["NOT_SOLID_VOLUME", "INCONSISTENT_NORMALS", "DEGENERATE_FACES"], title: "Not a valid solid", place: "Whole part" },
  { id: "thin", codes: ["THIN_WALL", "THIN_WALL_MOLDING", "THIN_BOSS", "TOO_THIN_SHEET"], title: "Walls too thin", place: "Walls" },
  { id: "draft", codes: ["INSUFFICIENT_DRAFT"], title: "Side walls need draft", place: "Side walls" },
  { id: "drain", codes: ["TRAPPED_VOLUME"], title: "Sealed cavity, no drain holes", place: "Sealed cavity" },
  { id: "corners", codes: ["SHARP_INTERNAL_CORNERS", "MISSING_FILLETS"], title: "Sharp inside corners", place: "Inside corners" },
  { id: "reach", codes: ["TOOL_REACH"], title: "Corners deeper than a cutter reaches", place: "Inside corners" },
  // Supports are the printer's setup (or turn the part): nothing in the design has to change.
  { id: "overhang", codes: ["OVERHANG"], title: "Overhangs need support", place: "Faces pointing down", noChange: "shop" },
  { id: "undercut", codes: ["UNDERCUT_MOLDING", "UNDERCUT"], title: "Undercuts", place: "Undercut faces" },
  { id: "thick", codes: ["THICK_WALL", "TOO_THICK_SHEET", "SHRINKAGE_RISK"], title: "Thick sections", place: "Thick sections" },
  { id: "flat", codes: ["CUPPING_RISK", "RESIDUAL_STRESS_RISK"], title: "Large flat area", place: "Flat faces", noChange: "shop" },
  { id: "bodies", codes: ["MULTIPLE_BODIES"], title: "More than one body", place: "Whole part" },
  { id: "round", codes: ["NOT_ROTATIONALLY_SYMMETRIC"], title: "Not a turned part", place: "Whole part", noChange: "method" },
  { id: "holes", codes: ["DEEP_HOLE", "HIGH_LD_RATIO", "SMALL_HOLE_SHEET"], title: "Deep or narrow holes", place: "Holes" },
  { id: "small", codes: ["SMALL_FEATURES", "FRAGILE_CORE"], title: "Features too small", place: "Small features" },
  { id: "aspect", codes: ["EXTREME_ASPECT_RATIO", "HIGH_RIB_RATIO"], title: "Tall, thin features", place: "Tall features" },
  { id: "uneven", codes: ["NON_UNIFORM_WALLS"], title: "Uneven walls", place: "Walls" },
  { id: "build", codes: ["EXCEEDS_BUILD_VOLUME"], title: "Too big for the machine", place: "Whole part" },
  { id: "fixture", codes: ["NO_FIXTURE_SURFACES"], title: "Nothing flat to hold it by", place: "Whole part" },
  { id: "bend", codes: ["SHARP_BEND", "BEND_RADIUS_UNDER_GAUGE"], title: "Bends too tight", place: "Bends" },
];

const BY_CODE = new Map<string, FamilyDef>();
for (const f of FAMILIES) for (const c of f.codes) BY_CODE.set(c, f);

/** Plain titles for engine codes that have no problem family of their own (never the code itself). */
const PLAIN_TITLE: Record<string, string> = {
  WIRE_CANNOT_REACH: "A closed-in face a wire can’t cut",
  SEALED_VOID_NO_ACCESS: "A sealed void no tool can reach",
  SEALED_VOID: "A sealed void inside",
  SEALED_VOID_SUPPORT: "Support sealed inside a void",
  CONDUCTIVITY_REQUIRED: "Needs a conductive material",
  NOT_SHEET_STOCK: "Too thick for sheet",
  BODIES_SHARE_EDGES: "Bodies touch along edges",
  SETUP_ACCESS_UNVERIFIED: "Tool access not confirmed",
  BUILD_REORIENTATION_REQUIRED: "Fits only turned on the plate",
  MACHINING_ALLOWANCE: "Needs machining after printing",
  PATTERN_TOOLING_REVIEW: "Pattern tooling to review",
  SINTERING_SHRINKAGE: "Shrinks when sintered",
  RIB_RULES_CHECK: "Ribs to check",
};

function titleFromCode(code: string): string {
  if (PLAIN_TITLE[code]) return PLAIN_TITLE[code];
  const words = code.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function familyOf(code: string): FamilyDef {
  const c = code.toUpperCase();
  return BY_CODE.get(c) ?? { id: `code:${c}`, codes: [c], title: titleFromCode(c), place: "Whole part" };
}

/** Process paperwork a rule pack asks for: real requirements, not design problems. */
const PAPERWORK = new Set([
  "UDI_MARKING",
  "TRACEABILITY_REQUIRED",
  "STERILIZATION_VALIDATION",
  "SPECIAL_PROCESSES",
  "PPAP_REQUIRED",
  "NACE_MR",
  "HYDROSTATIC_TEST",
  "FIRST_ARTICLE_INSPECTION",
  "DESIGN_HISTORY_FILE",
  "CONTROL_PLAN_REQUIRED",
  "BIOCOMPATIBILITY_REQUIRED",
  "API_PSL_LEVEL",
  "ANALYSIS_PARTIAL",
  "DECIMATED_MESH",
  "NON_STANDARD_GAUGE",
]);

export type NotListedKind = "setup" | "precision" | "paperwork" | "note";

/** Why a finding isn't listed as a problem, or null when it is one. Errors always are. */
export function notListedKind(i: Pick<Issue, "code" | "severity">): NotListedKind | null {
  if (i.severity === "error") return null;
  const c = i.code.toUpperCase();
  if (i.severity === "info") return "note";
  if (/_UNVERIFIED$|_REVIEW$|_CHECK$/.test(c)) return "setup";
  if (/_PRECISION$|_SAMPLED$|_UNAVAILABLE$/.test(c)) return "precision";
  if (PAPERWORK.has(c)) return "paperwork";
  return null;
}

/* ── what a required value means ───────────────────────────────────────── */

/**
 * For these findings the engine's `required_value` is a MAXIMUM (an overhang the
 * method allows, a thickest section, a hole depth ratio…); for every other one it
 * is a minimum (a wall, a draft, a fillet, a drain hole).
 */
const MAX_CODES = new Set([
  "OVERHANG",
  "SHRINKAGE_RISK",
  "RESIDUAL_STRESS_RISK",
  "CUPPING_RISK",
  "SHARP_BEND",
  "THICK_WALL",
  "EXTREME_ASPECT_RATIO",
  "DEEP_HOLE",
  "HIGH_LD_RATIO",
  "NON_UNIFORM_WALLS",
  "HIGH_RIB_RATIO",
  "TOO_THICK_SHEET",
]);

export type Direction = "min" | "max";

export function directionOf(code: string): Direction {
  return MAX_CODES.has(code.toUpperCase()) ? "max" : "min";
}

/* ── formatting ────────────────────────────────────────────────────────── */

export function n0(v: number): string {
  return Math.round(v).toLocaleString("en-US");
}

/** Engine prose in product typography: "0.8mm" → "0.8 mm", "2x" → "2×", ">=" → "at least". */
/** A long decimal from an engine message in three figures ("0.347954" → "0.348"); "(0.0%)" as "under 0.1%". */
export function plainNumbers(text: string): string {
  return text
    .replace(/-?\d+\.\d{4,}/g, (m) => {
      const n = Number(m);
      if (!Number.isFinite(n)) return m;
      return Math.abs(n) >= 100 ? n.toFixed(0) : Math.abs(n) >= 10 ? n.toFixed(1) : String(Number(n.toPrecision(3)));
    })
    .replace(/\((?:0\.0+|0)%\)/g, "(under 0.1%)");
}

/** A cost driver's derivation in plain figures: numbers in three figures, no "× region-labor ×1" that changes nothing. */
export function howText(how: string): string {
  return plainNumbers(how)
    .replace(/\s*×\s*region-labor\s*×1(?![\d.])/g, "")
    .replace(/region-labor\s*×/g, "regional labor ×");
}

export function tidy(text: string | null | undefined): string {
  return plainNumbers(String(text ?? ""))
    .replace(/(\d)\s?mm\b/g, "$1 mm")
    .replace(/(\d)mm([²³])/g, "$1 mm$2")
    .replace(/(\d)x\b/g, "$1×")
    .replace(/>=\s?/g, "at least ")
    .replace(/<=\s?/g, "at most ")
    .replace(/\s+—\s+/g, ": ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function firstSentence(text: string): string {
  const t = text.trim();
  const m = t.match(/^(.+?[.!?])(\s|$)/);
  return (m ? m[1] : t).trim();
}

export function unitText(unit: Issue["measurement_unit"] | null | undefined): string {
  return unit === "deg" ? "°" : unit === "mm" ? " mm" : unit === "percent" ? "%" : "";
}

/** "0.8 mm", "1°", "3.0 mm" in the unit the engine reported. */
export function measure(v: number | null | undefined, unit: Issue["measurement_unit"] | null | undefined): string | null {
  if (v == null || !Number.isFinite(v)) return null;
  if (unit === "deg") return `${v.toFixed(1)}°`;
  if (unit === "mm") return `${v.toFixed(1)} mm`;
  if (unit === "percent") return `${trimNum(v, 1)}%`;
  if (unit === "ratio") return `${trimNum(v, 2)} : 1`;
  return `${trimNum(v, 2)}${unitText(unit)}`;
}

function numIn(text: string, re: RegExp): number | null {
  const m = text.match(re);
  if (!m) return null;
  const v = Number(m[1].replace(/,/g, ""));
  return Number.isFinite(v) ? v : null;
}

/* ── the problem model ─────────────────────────────────────────────────── */

export interface ProblemMethod {
  code: string;
  name: string;
  short: string;
  severity: Issue["severity"];
  issue: Issue;
  /** "min": the method needs at least `need`; "max": it allows at most `need`. */
  dir: Direction;
  need: number | null;
  measured: number | null;
  unit: Issue["measurement_unit"] | null;
}

export interface Problem {
  id: string;
  title: string;
  place: string;
  codes: string[];
  severity: "error" | "warning";
  /** A whole-file finding (closed solid, bodies): it applies to every method. */
  universal: boolean;
  primary: Issue;
  /** One row per method that reported it, the most demanding first. */
  methods: ProblemMethod[];
  /** Methods it stops ("can't as drawn"); every method for a universal error. */
  blocks: string[];
  /** Methods it only flags. */
  warns: string[];
  /** Warning findings across methods (each method's finding counts once). */
  warnCount: number;
  faces: number[];
  /** Mesh triangles the findings flag. */
  faceCount: number | null;
  /** The CAD faces those triangles lie on (a STEP or IGES; null for an STL). */
  cadFaceCount: number | null;
  region: [number, number, number] | null;
  scope: "localized" | "whole_part";
  kind: Kind | null;
  noChange: "shop" | "method" | null;
  where: string;
}

export interface ProblemSet {
  problems: Problem[];
  /** "Not listed: 3 setup reviews and 2 process notes. They aren't design problems." or null. */
  notListed: string | null;
  /** Every engine process this part was judged for. */
  processes: string[];
}

interface Entry {
  process: string | null;
  issue: Issue;
}

const SEV: Record<string, number> = { error: 0, warning: 1, info: 2 };

/** Group the engine's findings into problems. Errors first, then by how many methods they touch. */
export function buildProblems(input: { validation: ValidationResult | null; cost: CostReport | null }): ProblemSet {
  const { validation, cost } = input;
  const entries: Entry[] = [];
  const processes = new Set<string>();
  if (validation) {
    for (const i of validation.universal_issues ?? []) entries.push({ process: null, issue: i });
    for (const p of validation.process_scores ?? []) {
      processes.add(p.process);
      for (const i of p.issues ?? []) entries.push({ process: p.process, issue: { ...i, process: i.process ?? p.process } });
    }
  }
  for (const e of cost?.estimates ?? []) processes.add(e.process);
  for (const f of cost?.engine_feasibility ?? []) processes.add(f.process);
  if (!validation && cost) {
    // No stored analysis: the cost record's blockers are the same Issues (errors only).
    const seen = new Set<string>();
    for (const e of cost.estimates ?? []) {
      for (const i of e.dfm_blocker_details ?? []) {
        const k = `${e.process}␟${i.code}`;
        if (seen.has(k)) continue;
        seen.add(k);
        entries.push({ process: e.process, issue: { ...i, process: i.process ?? e.process } });
      }
    }
  }

  const skipped = new Map<NotListedKind, Set<string>>();
  const groups = new Map<string, { fam: FamilyDef; entries: Entry[] }>();
  for (const en of entries) {
    const why = notListedKind(en.issue);
    if (why) {
      if (!skipped.has(why)) skipped.set(why, new Set());
      skipped.get(why)!.add(en.issue.code);
      continue;
    }
    const fam = familyOf(en.issue.code);
    if (!groups.has(fam.id)) groups.set(fam.id, { fam, entries: [] });
    groups.get(fam.id)!.entries.push(en);
  }

  const all = [...processes];
  const totalFaces = validation?.geometry?.faces ?? cost?.geometry?.face_count ?? null;
  const totalCad = validation?.geometry?.cad_faces ?? null;
  const problems: Problem[] = [];
  for (const { fam, entries: es } of groups.values()) {
    const sorted = [...es].sort((a, b) => (SEV[a.issue.severity] ?? 3) - (SEV[b.issue.severity] ?? 3));
    const primary = (sorted.find((e) => (e.issue.affected_faces_sample?.length ?? 0) > 0 && e.issue.severity === sorted[0].issue.severity) ?? sorted[0]).issue;
    const universal = es.some((e) => e.process == null);
    const blocks = new Set<string>();
    const warns = new Set<string>();
    let warnCount = 0;
    const perMethod = new Map<string, Entry>();
    for (const e of es) {
      if (e.process == null) {
        if (e.issue.severity === "error") all.forEach((p) => blocks.add(p));
        else warnCount += 1;
        continue;
      }
      if (e.issue.severity === "error") blocks.add(e.process);
      else {
        warns.add(e.process);
        warnCount += 1;
      }
      const prev = perMethod.get(e.process);
      if (!prev || (SEV[e.issue.severity] ?? 3) < (SEV[prev.issue.severity] ?? 3) || (prev.issue.required_value == null && e.issue.required_value != null)) perMethod.set(e.process, e);
    }
    for (const b of blocks) warns.delete(b);
    const methods: ProblemMethod[] = [...perMethod.values()].map(({ process, issue }) => ({
      code: process!,
      name: methodName(process),
      short: METHODS[process!]?.short ?? process!.toUpperCase(),
      severity: issue.severity,
      issue,
      dir: directionOf(issue.code),
      need: issue.required_value ?? needFromMessage(fam.id, issue.message),
      measured: issue.measured_value ?? null,
      unit: issue.measurement_unit ?? (fam.id === "drain" ? "mm" : null),
    }));
    methods.sort((a, b) => (SEV[a.severity] ?? 3) - (SEV[b.severity] ?? 3) || (a.need ?? 1e9) - (b.need ?? 1e9) || a.name.localeCompare(b.name));
    const withFaces = [...es].filter((e) => (e.issue.affected_faces_sample?.length ?? 0) > 0).sort((a, b) => (SEV[a.issue.severity] ?? 3) - (SEV[b.issue.severity] ?? 3) || (b.issue.affected_faces_sample!.length - a.issue.affected_faces_sample!.length));
    const faceIssue = withFaces[0]?.issue ?? null;
    const faces = (faceIssue?.affected_faces_sample ?? []).filter((n) => Number.isInteger(n) && n >= 0);
    const faceCount = es.reduce<number | null>((m, e) => (e.issue.affected_face_count != null && (m == null || e.issue.affected_face_count > m) ? e.issue.affected_face_count : m), null);
    const cadFaceCount = es.reduce<number | null>((m, e) => (e.issue.cad_face_count != null && (m == null || e.issue.cad_face_count > m) ? e.issue.cad_face_count : m), null);
    const regionIssue = es.find((e) => e.issue.region_center && e.issue.region_center.length === 3)?.issue ?? null;
    const scope = es.some((e) => e.issue.scope === "localized" || (e.issue.affected_faces_sample?.length ?? 0) > 0 || !!e.issue.region_center) ? "localized" : "whole_part";
    const p: Problem = {
      id: fam.id,
      title: fam.id === "bodies" ? bodiesTitle(primary.message) : fam.title,
      place: fam.place,
      codes: [...new Set(es.map((e) => e.issue.code))],
      severity: es.some((e) => e.issue.severity === "error") ? "error" : "warning",
      universal,
      primary,
      methods,
      blocks: [...blocks],
      warns: [...warns],
      warnCount,
      faces,
      faceCount: faceCount ?? (faces.length || null),
      cadFaceCount,
      region: regionIssue?.region_center ?? null,
      scope,
      kind: issueKind(primary.code) ?? (fam.id === "open" ? null : issueKind(faceIssue?.code ?? "")),
      noChange: fam.noChange ?? null,
      where: "",
    };
    p.where = whereLine(p, totalFaces, totalCad);
    problems.push(p);
  }
  problems.sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "error" ? -1 : 1) || b.blocks.length - a.blocks.length || b.warnCount - a.warnCount || a.title.localeCompare(b.title));
  return { problems, notListed: notListedLine(skipped), processes: all };
}

function bodiesTitle(message: string): string {
  const n = numIn(message, /(\d[\d,]*)\s+disconnected bod/i);
  return n && n > 1 ? `${n} bodies in one file` : "More than one body";
}

/** A need the engine states only in its message ("Needs >= 3.5mm drain holes"). */
function needFromMessage(fam: string, message: string): number | null {
  if (fam === "drain") return numIn(message, />=\s?([\d.]+)\s?mm/);
  if (fam === "overhang") return numIn(message, /exceed\s+([\d.]+)°/);
  return null;
}

function notListedLine(skipped: Map<NotListedKind, Set<string>>): string | null {
  const parts: string[] = [];
  const n = (k: NotListedKind) => skipped.get(k)?.size ?? 0;
  if (n("setup")) parts.push(`${n("setup")} setup ${n("setup") === 1 ? "review" : "reviews"}`);
  if (n("precision")) parts.push(`${n("precision")} measurement-precision ${n("precision") === 1 ? "note" : "notes"}`);
  if (n("paperwork")) parts.push(`${n("paperwork")} paperwork ${n("paperwork") === 1 ? "requirement" : "requirements"}`);
  if (n("note")) parts.push(`${n("note")} process ${n("note") === 1 ? "note" : "notes"}`);
  if (!parts.length) return null;
  const list = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
  return `Not listed: ${list}. They aren’t design problems.`;
}

/** Where on the part, from the engine's own counts and message. */
/** "8 of 11 faces" (a STEP's own faces, as its CAD tool counts them) or "169,370 mesh triangles". */
export function facesText(p: Pick<Problem, "faceCount" | "cadFaceCount">, totalFaces: number | null, totalCad: number | null = null): string | null {
  if (p.cadFaceCount != null) return totalCad ? `${n0(p.cadFaceCount)} of ${n0(totalCad)} faces` : `${n0(p.cadFaceCount)} ${p.cadFaceCount === 1 ? "face" : "faces"}`;
  if (p.faceCount == null) return null;
  return totalFaces ? `${n0(p.faceCount)} of ${n0(totalFaces)} mesh triangles` : `${n0(p.faceCount)} mesh ${p.faceCount === 1 ? "triangle" : "triangles"}`;
}

export function whereLine(p: Pick<Problem, "id" | "primary" | "faceCount" | "scope" | "methods"> & { cadFaceCount?: number | null }, totalFaces: number | null, totalCad: number | null = null): string {
  const msg = p.primary.message ?? "";
  const fc = p.faceCount;
  const fp = { faceCount: fc, cadFaceCount: p.cadFaceCount ?? null };
  switch (p.id) {
    case "open": {
      const e = numIn(msg, /has\s+(\d[\d,]*)\s+boundary edges/);
      return e != null ? `${n0(e)} open edges` : "Not a closed solid";
    }
    case "thin": {
      const every = fp.cadFaceCount != null ? !!totalCad && fp.cadFaceCount >= totalCad : fc != null && !!totalFaces && fc >= totalFaces;
      const f = facesText(fp, totalFaces, totalCad);
      if (f) return every ? `Every wall · ${f}` : f;
      const t = p.methods.find((m) => m.measured != null)?.measured;
      return t != null ? `Thinnest wall ${t.toFixed(1)} mm` : "Whole part";
    }
    case "draft": {
      const pct = numIn(msg, /\(([\d.]+)% of sidewall area\)/);
      return [pct != null ? `Side walls · ${trimNum(pct, 1)}% of side-wall area` : "Side walls", facesText(fp, null, totalCad)].filter(Boolean).join(" · ");
    }
    case "drain": {
      const v = numIn(msg, /\(([\d,.]+)\s?mm³\)/);
      return v != null ? `Sealed cavity · ${n0(v)} mm³` : "Sealed cavity";
    }
    case "corners": {
      const e = numIn(msg, /(\d[\d,]*)\s+sharp concave/);
      return e != null ? `${n0(e)} sharp inside corners` : "Inside corners";
    }
    case "overhang": {
      // The part's own steepest overhang (degrees past vertical), not one process's limit:
      // each process allows a different angle (FDM 45°, resin 19°), and the rows below say which.
      const steep = p.methods.reduce<number | null>((m, x) => (x.measured != null && (m == null || x.measured > m) ? x.measured : m), null);
      const f = facesText(fp, null, totalCad);
      return f ? `${f}${steep != null ? ` · steepest ${trimNum(steep, 0)}° past vertical` : ""}` : "Faces pointing down";
    }
    case "flat": {
      const area = numIn(msg, /\(([\d,.]+)\s?mm²/);
      return area != null ? `${n0(area)} mm² flat${/downward/i.test(msg) ? ", facing down" : ""}` : "Flat faces";
    }
    case "thick": {
      const t = numIn(msg, /section\s+([\d.]+)\s?mm/);
      return t != null ? `Thickest section ${trimNum(t, 2)} mm` : "Thick sections";
    }
    case "bodies": {
      const b = numIn(msg, /(\d[\d,]*)\s+disconnected/);
      return b != null ? `Whole part · ${b} disconnected bodies` : "Whole part";
    }
    default: {
      const f = facesText(fp, null, totalCad);
      if (f) return f;
      return p.scope === "whole_part" ? "Whole part" : "On the part";
    }
  }
}

/* ── one problem, for one method ───────────────────────────────────────── */

export interface ProblemFig {
  k: string;
  v: string;
  s: string;
  tone?: "ok" | "warn" | "bad";
}

function lower(name: string): string {
  return name.charAt(0).toLowerCase() + name.slice(1);
}

/** The measured figure, honest about what the engine reported. */
export function measuredFig(p: Problem, m: ProblemMethod | null): ProblemFig {
  const msg = p.primary.message ?? "";
  if (p.id === "open") {
    const e = numIn(msg, /has\s+(\d[\d,]*)\s+boundary edges/);
    return { k: "Open edges", v: e != null ? n0(e) : "Open", s: "not a closed solid", tone: "bad" };
  }
  if (p.id === "draft") {
    const v = m?.measured ?? p.primary.measured_value ?? null;
    if (v != null) return { k: "Measured", v: `${v.toFixed(1)}°`, s: "smallest draft", tone: "bad" };
    const need = m?.need ?? p.primary.required_value ?? 1;
    return { k: "Measured", v: `Under ${trimNum(need, 1)}°`, s: "angle not reported", tone: "bad" };
  }
  if (p.id === "drain") {
    const v = numIn(msg, /\(([\d,.]+)\s?mm³\)/);
    return { k: "Sealed cavity", v: v != null ? `${n0(v)} mm³` : "Sealed", s: "no way out", tone: "bad" };
  }
  if (p.id === "corners") {
    const e = numIn(msg, /(\d[\d,]*)\s+sharp concave/);
    return { k: "Measured", v: e != null ? n0(e) : "Sharp", s: "sharp inside corners", tone: p.severity === "error" ? "bad" : "warn" };
  }
  const v = m?.measured ?? p.primary.measured_value ?? null;
  const unit = m?.unit ?? p.primary.measurement_unit ?? null;
  if (v != null) return { k: "Measured", v: measure(v, unit)!, s: p.id === "thin" ? "thinnest wall" : p.id === "thick" ? "thickest section" : "on the part", tone: (m?.severity ?? p.severity) === "error" ? "bad" : "warn" };
  if (p.cadFaceCount != null) return { k: "Faces", v: n0(p.cadFaceCount), s: p.where.split(" · ")[0].toLowerCase() };
  return { k: "Triangles", v: p.faceCount != null ? n0(p.faceCount) : "—", s: p.where.split(" · ")[0].toLowerCase() };
}

/** "1°", "0.8 mm", "45°" for a required value in the engine's unit. */
export function needText(m: Pick<ProblemMethod, "need" | "unit">): string | null {
  if (m.need == null) return null;
  return m.unit === "deg" ? `${trimNum(m.need, 1)}°` : measure(m.need, m.unit) ?? String(m.need);
}

/** How far the measurement is past the rule: short of a minimum, or over a maximum. */
export function gap(m: Pick<ProblemMethod, "need" | "measured" | "dir">): number | null {
  if (m.need == null || m.measured == null) return null;
  return Math.max(0, m.dir === "max" ? m.measured - m.need : m.need - m.measured);
}

export function problemFigs(p: Problem, m: ProblemMethod | null, pricedOf: number): ProblemFig[] {
  if (p.id === "open") {
    return [measuredFig(p, m), { k: "Needs", v: "Closed solid", s: "every process" }, { k: "Priced", v: `0 of ${pricedOf}`, s: "needs a volume", tone: "bad" }];
  }
  const figs: ProblemFig[] = [measuredFig(p, m)];
  const nt = m ? needText(m) : null;
  const rules = p.id === "draft" ? draftRules(m) : null;
  if (m && rules && rules.inside !== rules.outside) figs.push({ k: "Needs", v: `${trimNum(rules.outside, 1)}° out · ${trimNum(rules.inside, 1)}° in`, s: `for ${lower(m.name)}: outside and inside walls` });
  else if (m && nt) figs.push({ k: m.dir === "max" ? "Allows" : "Needs", v: m.dir === "max" ? `${nt} at most` : nt, s: `for ${lower(m.name)}` });
  else if (m) figs.push({ k: "For", v: m.name, s: m.severity === "error" ? "can’t as drawn" : "check first" });
  const g = m ? gap(m) : null;
  if (m && g != null && (m.unit === "mm" || m.unit === "deg" || m.unit === "percent")) {
    const v = m.unit === "mm" ? `${g.toFixed(1)} mm` : m.unit === "deg" ? `${trimNum(g, 1)}°` : `${trimNum(g, 1)}%`;
    const s = p.id === "thin" ? (p.where.startsWith("Every wall") ? "every wall" : "thinnest wall") : p.id === "draft" ? "smallest draft" : m.dir === "max" ? "past the limit" : "below the minimum";
    figs.push({ k: m.dir === "max" ? "Over by" : "Short by", v, s, tone: "bad" });
  } else if (p.cadFaceCount != null && figs[0].k !== "Faces") {
    figs.push({ k: "Faces", v: n0(p.cadFaceCount), s: p.id === "draft" ? "side faces" : "flagged" });
  } else if (p.faceCount != null && figs[0].k !== "Faces" && figs[0].k !== "Triangles") {
    figs.push({ k: "Triangles", v: n0(p.faceCount), s: p.id === "draft" ? "on side walls" : "flagged" });
  }
  return figs.slice(0, 3);
}

/** The words on the part next to the pin. */
export function callout(p: Problem, m: ProblemMethod | null): { main: string; sub: string } {
  const msg = p.primary.message ?? "";
  const name = m ? lower(m.name) : "every process";
  if (p.id === "open") {
    const e = numIn(msg, /has\s+(\d[\d,]*)\s+boundary edges/);
    return { main: e != null ? `${n0(e)} open edges` : "Open shell", sub: "every process needs a closed solid" };
  }
  if (p.id === "draft") {
    const need = m?.need ?? 1;
    const meas = m?.measured ?? null;
    return { main: meas != null ? `${meas.toFixed(1)}° here` : `Under ${trimNum(need, 1)}° here`, sub: `needs ${trimNum(need, 1)}° for ${name}` };
  }
  if (p.id === "drain") {
    const v = numIn(msg, /\(([\d,.]+)\s?mm³\)/);
    return { main: v != null ? `Sealed, ${n0(v)} mm³` : "Sealed cavity", sub: m?.need != null ? `needs drain holes of ${trimNum(m.need, 1)} mm for ${m.short}` : `no drain holes for ${name}` };
  }
  if (p.id === "corners") {
    const e = numIn(msg, /(\d[\d,]*)\s+sharp concave/);
    return { main: e != null ? `${n0(e)} sharp inside corners` : "Sharp inside corners", sub: m?.need != null ? `${name} needs ${trimNum(m.need, 1)} mm fillets` : name };
  }
  const meas = measure(m?.measured ?? null, m?.unit ?? null);
  const need = m ? needText(m) : null;
  return { main: meas ? `${meas} here` : p.title, sub: need ? `${m!.dir === "max" ? `at most ${need}` : `needs ${need}`} for ${name}` : m ? `for ${name}` : p.where };
}

/** The reason in plain words, from the measured values. */
export function plainReason(p: Problem, m: ProblemMethod | null, pricedOf: number): string {
  const msg = p.primary.message ?? "";
  const name = m?.name ?? "Every process";
  const verdict = (m?.severity ?? p.severity) === "error" ? "it can’t make this part as drawn" : "it’s flagged to check first";
  switch (p.id) {
    case "open": {
      const e = numIn(msg, /has\s+(\d[\d,]*)\s+boundary edges/);
      return `The file doesn’t enclose a volume${e != null ? `: ${n0(e)} edges are open` : ""}. Every process needs a closed solid, and without a volume nothing can be priced${pricedOf ? ` (0 of ${pricedOf} processes have a price)` : ""}.`;
    }
    case "thin":
      if (m?.measured != null && m.need != null) return `The thinnest wall measures ${m.measured.toFixed(1)} mm. ${name} needs at least ${m.need.toFixed(1)} mm, so ${verdict}.`;
      break;
    case "draft": {
      const need = m?.need ?? 1;
      const breakdown = (m?.issue.message ?? "").match(/Smallest draft:\s*[\d.]+°\s*\(([^)]+)\)/)?.[1] ?? null;
      const lead = m?.measured != null ? `The smallest draft on the side walls is ${m.measured.toFixed(1)}°${breakdown ? ` (${breakdown})` : ""}.` : `The side walls are straight up and down: under ${trimNum(need, 1)}° of taper.`;
      return `${lead} A molded or cast part has to slide out of its tool, so ${lower(name)} needs at least ${trimNum(need, 1)}° of taper on them.`;
    }
    case "drain": {
      const v = numIn(msg, /\(([\d,.]+)\s?mm³\)/);
      return `The part has a sealed cavity${v != null ? ` of ${n0(v)} mm³` : ""} with no way out. Material is left inside it, so ${lower(name)} needs drain holes${m?.need != null ? ` of at least ${trimNum(m.need, 1)} mm` : ""}.`;
    }
    case "corners":
      if (m?.need != null) return `${tidy(firstSentence(m.issue.message))} ${name} needs a fillet of at least ${trimNum(m.need, 1)} mm there.`;
      break;
  }
  if (m && m.measured != null && m.need != null) {
    const meas = measure(m.measured, m.unit);
    const need = needText(m);
    return `${tidy(firstSentence(m.issue.message))} ${name} ${m.dir === "max" ? `allows at most ${need}; this is ${meas}` : `needs at least ${need}; this is ${meas}`}, so ${verdict}.`;
  }
  return tidy(m?.issue.message ?? p.primary.message);
}

/** Why the rule exists and who says so. No citation: the engine's own check. */
export function ruleOf(p: Problem, m: ProblemMethod | null): { text: string; source: string } {
  const issue = m?.issue ?? p.primary;
  const c = issue.citation;
  const applies = m ? ` · applies to ${lower(m.name)}` : "";
  if (c && (c.text || c.standard)) {
    const src = c.standard ? `${c.standard}${c.clause ? ` ${c.clause}` : ""}` : c.clause ? `Clause ${c.clause}, no standard named` : "No standard named";
    return { text: tidy(c.text || firstSentence(issue.fix_suggestion ?? issue.message)), source: `${src}${applies}` };
  }
  const why = p.id === "open" ? "All manufacturing processes require a closed solid." : tidy(firstSentence(issue.fix_suggestion ?? issue.message));
  return { text: why, source: `ScaleCAD check, no external standard${applies}` };
}

function joinWords(xs: string[]): string {
  if (xs.length <= 1) return xs[0] ?? "";
  return `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

/** The change to make, and what else the engine says. */
export function fixText(p: Problem, m: ProblemMethod | null, alternative: string | null): { fix: string; alt: string | null } {
  if (p.id === "thin" && m?.need != null) {
    const at = m.need;
    const covered = p.methods.filter((x) => x.need != null && x.need <= at + 1e-9).map((x) => lower(x.name));
    const more = new Map<number, string[]>();
    for (const x of p.methods) if (x.need != null && x.need > at + 1e-9) (more.get(x.need) ?? more.set(x.need, []).get(x.need)!).push(lower(x.name));
    const rest = [...more.entries()].sort((a, b) => a[0] - b[0]).map(([need, names]) => `${joinWords([...new Set(names)])} ${need.toFixed(1)} mm`);
    const alt = [covered.length ? `That covers ${joinWords([...new Set(covered)])}.` : null, rest.length ? `Others need more: ${rest.join(", ")}.` : null, alternative ? tidy(alternative) : null].filter(Boolean).join(" ");
    return { fix: `Make the walls at least ${at.toFixed(1)} mm thick.`, alt: alt || null };
  }
  if (p.id === "draft" && m?.need != null) {
    const others = p.methods.filter((x) => x.code !== m.code && x.need != null && x.need !== m.need).map((x) => `${lower(x.name)} ${trimNum(x.need!, 1)}°`);
    const alt = [alternative ? tidy(alternative) : null, others.length ? `Others need: ${joinWords(others)}.` : null].filter(Boolean).join(" ");
    const r = draftRules(m);
    if (r && r.inside !== r.outside) {
      const short = (m.issue.breakdown ?? []).filter((b) => b.faces > 0).map((b) => b.walls);
      const which = short.length === 1 ? `the ${short[0]} walls` : null;
      const fix = which
        ? `Add at least ${trimNum(short[0] === "inside" ? r.inside : r.outside, 1)}° of draft to ${which}, along the file’s Z axis, the pull direction the check uses. The ${short[0] === "inside" ? "outside" : "inside"} walls meet their ${trimNum(short[0] === "inside" ? r.outside : r.inside, 1)}°.`
        : `Add at least ${trimNum(r.outside, 1)}° of draft to the outside walls and ${trimNum(r.inside, 1)}° to the inside walls (a bore, the inside of a box), along the file’s Z axis, the pull direction the check uses.`;
      return { fix, alt: alt || null };
    }
    return { fix: `Add at least ${trimNum(m.need, 1)}° of draft to the side walls, along the file’s Z axis, the pull direction the check uses.`, alt: alt || null };
  }
  const src = m?.issue ?? p.primary;
  const fix = tidy(firstSentence(src.fix_suggestion ?? "") || src.message);
  const rest = tidy((src.fix_suggestion ?? "").slice(firstSentence(src.fix_suggestion ?? "").length));
  const alt = [rest || null, alternative ? tidy(alternative) : null].filter(Boolean).join(" ");
  return { fix, alt: alt || null };
}

/** A draft rule's two angles, outside and inside walls (the engine's breakdown), or null for one rule. */
export function draftRules(m: ProblemMethod | null): { outside: number; inside: number } | null {
  const b = m?.issue.breakdown;
  if (!b?.length) return null;
  const outside = b.find((x) => x.walls === "outside")?.need_deg;
  const inside = b.find((x) => x.walls === "inside")?.need_deg;
  if (outside == null && inside == null) return null;
  return { outside: outside ?? inside!, inside: inside ?? outside! };
}

/** The engine's "Alternative: …" for this problem, from the priority list. */
export function alternativeOf(validation: ValidationResult | null, p: Problem): string | null {
  for (const f of validation?.priority_fixes ?? []) {
    if (!p.codes.includes(f.code)) continue;
    const m = (f.fix ?? "").match(/Alternative:\s*([\s\S]+)$/);
    if (m) return m[1].trim();
  }
  return null;
}

/** The method the sheet opens on: the one asked for, the page's pick, else the first listed. */
export function pickMethod(p: Problem, asked: string | null | undefined, fallback: string | null | undefined): ProblemMethod | null {
  return p.methods.find((m) => m.code === asked) ?? p.methods.find((m) => m.code === fallback) ?? p.methods[0] ?? null;
}

/** "−0.3 mm", "under 1°", "+12°": how far each method's rule is missed, for the radio list. */
export function shortText(p: Problem, m: ProblemMethod): string {
  if (m.need == null) return m.severity === "error" ? "blocks" : "check";
  const g = gap(m);
  const sign = m.dir === "max" ? "+" : "−";
  if (g != null && m.unit === "mm") return `${sign}${g.toFixed(1)} mm`;
  if (g != null && m.unit === "deg") return `${sign}${trimNum(g, 1)}°`;
  if (g != null && m.unit === "percent") return `${sign}${trimNum(g, 1)}%`;
  if (g != null && m.unit === "ratio") return `${sign}${trimNum(g, 2)}`;
  if (m.unit === "deg") return m.dir === "max" ? `over ${trimNum(m.need, 1)}°` : `under ${trimNum(m.need, 1)}°`;
  return m.severity === "error" ? "blocks" : "check";
}

/** The radio list's column head: needs and short by, or allows and over by. */
export function methodHead(p: Problem): string {
  return p.methods.some((m) => m.dir === "max") && p.methods.every((m) => m.dir === "max" || m.need == null) ? "allows at most · over by" : "needs · short by";
}

export function findProblem(set: ProblemSet, id: string | null | undefined): Problem | null {
  return set.problems.find((p) => p.id === id) ?? null;
}

/** Which problem a method's own finding belongs to (for "See the problem" from the Make lens). */
export function problemForIssue(set: ProblemSet, code: string | null | undefined): Problem | null {
  if (!code) return null;
  const fam = familyOf(code);
  return set.problems.find((p) => p.id === fam.id) ?? null;
}

/** Whether a problem applies to a process (null: every process): it reported it, or it applies to the whole file. */
export function appliesTo(p: Pick<Problem, "universal" | "methods" | "blocks" | "warns">, code: string | null): boolean {
  if (!code) return true;
  return p.universal || p.blocks.includes(code) || p.warns.includes(code) || p.methods.some((m) => m.code === code);
}

/** "Stops filament printing (FDM/FFF): needs at least 0.8 mm, measured 0.5 mm", for one process in the list. */
export function forProcessLine(p: Problem, code: string, label: string): string | null {
  const m = p.methods.find((x) => x.code === code);
  if (!m) return p.universal ? `${p.severity === "error" ? "Stops" : "Flags"} every process, ${lower(label)} too` : null;
  const verb = m.severity === "error" ? "Stops" : "Flags";
  const nt = needText(m);
  const meas = m.measured != null ? measure(m.measured, m.unit) : null;
  const need = nt == null ? null : m.dir === "max" ? `allows at most ${nt}` : `needs at least ${nt}`;
  return `${verb} ${lower(label)}${need ? `: ${need}${meas ? `, measured ${meas}` : ""}` : ""}`;
}
