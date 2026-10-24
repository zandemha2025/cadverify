/**
 * The "Fix it in your CAD tool" steps, read from the vendor-verified data in
 * `./cad-steps.ts` (owned by another builder; not edited here). A problem maps to
 * one verified fix (draft, thicken, fillet, drain hole, heal), followed by that
 * tool's STEP export. A step set that isn't verified is never shown: the dialog
 * links to the vendor's own page for that feature instead. A problem with no
 * verified fix gets only the export steps, said plainly.
 *
 * Pure (runs under node --test).
 */
import { CAD_STEPS, CAD_TOOL_NAMES, type CadFix, type CadToolId } from "./cad-steps.ts";

export interface CadTool {
  id: CadToolId;
  label: string;
}

export const CAD_TOOLS: CadTool[] = (Object.keys(CAD_TOOL_NAMES) as CadToolId[]).map((id) => ({ id, label: CAD_TOOL_NAMES[id] }));

const FIX_OF: Record<string, CadFix> = {
  draft: "draft",
  thin: "thicken",
  corners: "fillet",
  drain: "drain_hole",
  open: "heal",
  solid: "heal",
};

export function cadFixOf(problemId: string): CadFix | null {
  return FIX_OF[problemId] ?? null;
}

export interface CadPath {
  /** The steps to show, the fix then the export; empty when the fix's steps aren't verified. */
  steps: string[];
  /** The tool's feature for the fix, e.g. "Draft (Neutral Plane)", or null. */
  feature: string | null;
  /** The vendor pages the steps were checked against. */
  sources: string[];
  /** The fix has verified steps for this tool. */
  verified: boolean;
  /** No verified fix for this kind of problem at all (export steps only). */
  noFix: boolean;
  /** When the fix's steps aren't verified: the vendor's page for that feature. */
  help: string | null;
}

export function cadPath(tool: CadToolId, problemId: string): CadPath {
  const fix = cadFixOf(problemId);
  const exp = CAD_STEPS.export_step[tool];
  const expSteps = exp?.verified ? exp.steps : [];
  const expSrc = exp?.verified ? [exp.source] : [];
  if (!fix) return { steps: expSteps, feature: null, sources: expSrc, verified: false, noFix: true, help: null };
  const set = CAD_STEPS[fix]?.[tool];
  if (!set || !set.verified) return { steps: [], feature: set?.feature ?? null, sources: [], verified: false, noFix: false, help: set?.source ?? null };
  return { steps: [...set.steps, ...expSteps], feature: set.feature, sources: [set.source, ...expSrc], verified: true, noFix: false, help: null };
}

/** The draft steps with the angles the check asks for, in place of "the outside angle" and
 *  "the inside angle" (de-02): 1° outside and 2° inside for molding, say. */
export function withDraftAngles(steps: string[], outside: number | null, inside: number | null): string[] {
  const deg = (v: number) => `${Number.isInteger(v) ? v : Number(v.toFixed(1))}°`;
  return steps.map((s) => {
    let out = s;
    if (outside != null) out = out.replace(/the outside angle/g, `${deg(outside)} (the outside walls’ rule)`);
    if (inside != null) out = out.replace(/the inside angle/g, `${deg(inside)} (the inside walls’ rule)`);
    return out;
  });
}
