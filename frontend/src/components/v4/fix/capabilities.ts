/**
 * What ScaleCAD can fix itself, today, and what it can't. Stated exactly:
 *  - an open mesh: mesh repair on a copy (a pilot tool, POST /validate/repair);
 *  - a Design Studio part: a new revision with a changed template parameter
 *    (wall or thickness; draft on the plate and the open enclosure, not the bracket);
 *  - on an uploaded file's kept source, what the server reports it can do itself
 *    (GET /parts/{hash}/fixes: drain holes, rounded inside corners, sewing faces
 *    into a solid), each on a copy that is re-checked in the same request;
 *  - anything else is a change in the user's CAD tool.
 *
 * Pure: no React, no fetch (runs under node --test).
 */
import type { DesignPlan } from "@/lib/designs-api";
import { MAX_DRAFT_DEG, draftAngleOf, supportsDraft } from "../../../lib/design-plan.ts";
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

/** What the server can fix itself for one problem family on this file (GET /parts/{hash}/fixes). */
export interface ServerFix {
  can: boolean;
  fix: string | null;
  label: string;
  method: string;
  param: string | null;
  unit: string | null;
  bounds: [number, number] | null;
  /** The parameter it would use, from the findings. */
  value: number | null;
  whyNot: string | null;
  /** What the last attempt's re-check said, when there was one. */
  lastAttempt: string | null;
}

export interface ServerFixes {
  /** Problem family ids it can fix on this file. */
  families: string[];
  byFamily: Record<string, ServerFix>;
  /** Fixes this server can run at all (for "what ScaleCAD fixes today"). */
  available: { id: string; label: string }[];
}

export interface FixOrigin {
  fileType: string;
  /** The file isn't a closed solid (the engine's NON_WATERTIGHT). */
  open: boolean;
  studio: StudioOrigin | null;
  server: ServerFixes | null;
  /**
   * The account is on the Pilot plan (GET /api/auth/me/usage plan). Mesh repair and
   * ScaleCAD's own fixes need it (backend require_paid_access); a new Design Studio
   * revision doesn't. null when the plan isn't known yet.
   */
  pilot?: boolean | null;
}

/** A fix route that needs the Pilot plan, for an account that isn't on it. */
export function needsPilot(route: FixRoute, origin: FixOrigin): boolean {
  return !!route && route.kind !== "studio" && origin.pilot === false;
}

export type StudioParam = { key: string; label: string; value: number; unit: "mm" | "°" };

export type FixRoute = { kind: "repair" } | { kind: "studio"; param: StudioParam } | { kind: "server"; fix: ServerFix } | null;

/** The template parameter that changes this problem, when the template has one. */
export function studioParam(plan: DesignPlan, problemId: string): StudioParam | null {
  if (problemId === "thin") {
    if (plan.kind === "enclosure") return { key: "wall_thickness_mm", label: "Wall", value: plan.wall_thickness_mm, unit: "mm" };
    if (plan.kind === "bracket" || plan.kind === "plate") return { key: "thickness_mm", label: "Thickness", value: plan.thickness_mm, unit: "mm" };
  }
  if (problemId === "draft" && supportsDraft(plan.kind)) {
    // draft_angle_deg (0–10°, release along +Z); a stored plan leaves out a zero draft.
    return { key: "draft_angle_deg", label: "Draft", value: draftAngleOf(plan) ?? 0, unit: "°" };
  }
  return null;
}

export function fixRoute(p: Problem, origin: FixOrigin): FixRoute {
  if (origin.studio) {
    const param = studioParam(origin.studio.plan, p.id);
    if (param) return { kind: "studio", param };
  }
  // The server's own fix on a copy of the kept CAD (it keeps a STEP or IGES a solid model) …
  const sf = origin.server?.byFamily[p.id];
  if (sf?.can && sf.fix && origin.server!.families.includes(p.id)) return { kind: "server", fix: sf };
  // … else mesh repair for an open shell.
  if (p.id === "open" && origin.open) return { kind: "repair" };
  return null;
}

/** The chip on a problem row: who fixes it. */
export function whoFixes(p: Problem, origin: FixOrigin, millingWorks: boolean): { label: string; tone: "c-ok" | "c-unk" } {
  const r = fixRoute(p, origin);
  if (r) return needsPilot(r, origin) ? { label: "ScaleCAD can fix · Pilot", tone: "c-unk" } : { label: "ScaleCAD can fix", tone: "c-ok" };
  if (p.noChange === "shop") return { label: "At the shop", tone: "c-unk" };
  if (p.noChange === "method") return p.id === "round" && millingWorks ? { label: "Use milling", tone: "c-ok" } : { label: "Another method", tone: "c-unk" };
  return { label: "In your CAD", tone: "c-unk" };
}

/** "ScaleCAD can’t edit this STL…": the honest line under the fix actions. */
export function canFixLine(p: Problem, origin: FixOrigin): string {
  const r = fixRoute(p, origin);
  if (r && needsPilot(r, origin)) return `On the Pilot plan ScaleCAD can ${r.kind === "repair" ? "try a mesh repair" : r.kind === "server" ? `${r.fix.label.charAt(0).toLowerCase()}${r.fix.label.slice(1)}` : "fix this"} on a copy of your file. Your plan covers checks, so this one is a change in your CAD tool.`;
  if (r?.kind === "repair") return "Mesh repair is a pilot tool. It works on a copy; your file stays as it is.";
  if (r?.kind === "studio") return `Made in Design Studio, so ScaleCAD can make revision ${origin.studio!.currentRevision + 1} with a new ${r.param.label.toLowerCase()} and check it.`;
  if (r?.kind === "server") return `ScaleCAD can ${r.fix.label.charAt(0).toLowerCase()}${r.fix.label.slice(1)} on a copy of your file and check the copy, as a pilot tool. Your file stays as it is.`;
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
    if (!supportsDraft(plan.kind)) return "This template has no draft angle.";
    if (v < 0 || v > MAX_DRAFT_DEG) return `Use 0° to ${MAX_DRAFT_DEG}°.`;
    return null;
  }
  return null;
}

function trimMm(v: number): string {
  return String(Math.round(v * 10) / 10);
}
