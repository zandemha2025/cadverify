/**
 * What ScaleCAD can fix itself, today, and what it can't. Stated exactly:
 *  - an open mesh: mesh repair on a copy (a pilot tool, POST /validate/repair);
 *  - a Design Studio part: a new revision with a changed template parameter
 *    (wall or thickness; draft on the plate and the open enclosure, not the bracket);
 *  - anything else on an uploaded CAD file is a change in the user's CAD tool.
 * `server` is the seam for a backend that fixes some problems in uploaded CAD
 * itself (it reports, per finding, whether it can); null until that exists.
 *
 * Pure: no React, no fetch (runs under node --test).
 */
import type { DesignPlan } from "@/lib/designs-api";
import type { Problem } from "./problems.ts";

export interface StudioOrigin {
  designId: string;
  designName: string;
  /** The revision this part is. */
  revision: number;
  currentRevision: number;
  plan: DesignPlan;
  volumeCm3: number | null;
}

/** What a server-side fixer reported it can do for this part (the seam; not built yet). */
export interface ServerFixes {
  /** Problem family ids it can fix on this file. */
  families: string[];
}

export interface FixOrigin {
  fileType: string;
  /** The file isn't a closed solid (the engine's NON_WATERTIGHT). */
  open: boolean;
  studio: StudioOrigin | null;
  server: ServerFixes | null;
}

export type StudioParam = { key: string; label: string; value: number; unit: "mm" | "°" };

export type FixRoute = { kind: "repair" } | { kind: "studio"; param: StudioParam } | { kind: "server" } | null;

/** The template parameter that changes this problem, when the template has one. */
export function studioParam(plan: DesignPlan, problemId: string): StudioParam | null {
  if (problemId === "thin") {
    if (plan.kind === "enclosure") return { key: "wall_thickness_mm", label: "Wall", value: plan.wall_thickness_mm, unit: "mm" };
    if (plan.kind === "bracket" || plan.kind === "plate") return { key: "thickness_mm", label: "Thickness", value: plan.thickness_mm, unit: "mm" };
  }
  if (problemId === "draft" && (plan.kind === "plate" || plan.kind === "enclosure")) {
    // draft_angle_deg (0–10°, release along +Z) is left out of a stored plan when it's 0.
    const v = (plan as unknown as { draft_angle_deg?: number }).draft_angle_deg ?? 0;
    return { key: "draft_angle_deg", label: "Draft", value: v, unit: "°" };
  }
  return null;
}

export function fixRoute(p: Problem, origin: FixOrigin): FixRoute {
  if (p.id === "open" && origin.open) return { kind: "repair" };
  if (origin.studio) {
    const param = studioParam(origin.studio.plan, p.id);
    if (param) return { kind: "studio", param };
  }
  if (origin.server?.families.includes(p.id)) return { kind: "server" };
  return null;
}

/** The chip on a problem row: who fixes it. */
export function whoFixes(p: Problem, origin: FixOrigin, millingWorks: boolean): { label: string; tone: "c-ok" | "c-unk" } {
  if (fixRoute(p, origin)) return { label: "ScaleCAD can fix", tone: "c-ok" };
  if (p.noChange === "shop") return { label: "At the shop", tone: "c-unk" };
  if (p.noChange === "method") return p.id === "round" && millingWorks ? { label: "Use milling", tone: "c-ok" } : { label: "Another method", tone: "c-unk" };
  return { label: "In your CAD", tone: "c-unk" };
}

/** "ScaleCAD can’t edit this STL…": the honest line under the fix actions. */
export function canFixLine(p: Problem, origin: FixOrigin): string {
  const r = fixRoute(p, origin);
  if (r?.kind === "repair") return "Mesh repair is a pilot tool. It works on a copy; your file stays as it is.";
  if (r?.kind === "studio") return `Made in Design Studio, so ScaleCAD can make revision ${origin.studio!.currentRevision + 1} with a new ${r.param.label.toLowerCase()} and check it.`;
  if (r?.kind === "server") return "ScaleCAD can change this on a copy of your file and check the copy. Your file stays as it is.";
  if (origin.studio) return `Made in Design Studio, but ${p.title.toLowerCase()} isn’t a template parameter. Download the STEP and change it in your CAD tool.`;
  const ext = origin.fileType ? `this ${origin.fileType.toUpperCase()}` : "this file";
  return `ScaleCAD can’t edit ${ext}. It gives the steps, prices the result and checks the file you upload.`;
}

/** Validate a new template value against the generator's own bounds (backend designs/schema.py). */
export function studioValueProblem(plan: DesignPlan, key: string, raw: string): string | null {
  const v = Number(String(raw).replace(",", ".").trim());
  if (!String(raw).trim() || !Number.isFinite(v)) return "Enter a number.";
  if (plan.kind === "enclosure" && key === "wall_thickness_mm") {
    // The generator needs wall × 4 < the smaller of width and depth, and wall × 2 < height.
    const max = Math.min(Math.min(plan.width_mm, plan.depth_mm) / 4, plan.height_mm / 2, 50);
    if (v < 0.5 || v >= max) return `Use 0.5 mm or more, and under ${trimMm(max)} mm for a ${trimMm(plan.width_mm)} × ${trimMm(plan.depth_mm)} × ${trimMm(plan.height_mm)} mm enclosure.`;
    return null;
  }
  if (plan.kind === "bracket" && key === "thickness_mm") {
    const max = Math.min(plan.width_mm, plan.height_mm) / 2;
    if (v < 0.5 || v >= max) return `Use 0.5 mm or more, and under ${trimMm(max)} mm for this bracket.`;
    return null;
  }
  if (plan.kind === "plate" && key === "thickness_mm") {
    if (v < 0.5 || v > 100) return "Use 0.5 to 100 mm.";
    return null;
  }
  if (key === "draft_angle_deg") {
    if (v < 0 || v > 10) return "Use 0° to 10°.";
    return null;
  }
  return null;
}

function trimMm(v: number): string {
  return String(Math.round(v * 10) / 10);
}
