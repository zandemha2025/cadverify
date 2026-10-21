/**
 * How one mesh repair ended, in the words the screen uses (K2 progress, K3 after).
 * Every attempt lands in exactly one outcome, from the engine's own answer
 * (backend repair_service.repair_outcome): repaired, closed but the shape changed,
 * partly closed, not repaired, or nothing to repair. Then the next best thing to
 * do, in order: ScaleCAD sewing the faces (STEP/IGES, when the server offers it),
 * the steps in the user's CAD tool, uploading a fixed file.
 *
 * Pure: no React, no fetch (runs under node --test).
 */
import type { RepairOpenings, RepairOutcomeKind, RepairResult } from "@/lib/api";

export type { RepairOutcomeKind };

/** The outcome, also for responses from before the API said it. */
export function outcomeOf(r: Pick<RepairResult, "outcome" | "repair_applied" | "repair_details">): RepairOutcomeKind {
  if (r.outcome) return r.outcome;
  if (!r.repair_applied) return "not_repaired";
  const d = r.repair_details;
  return d.volume_warning || d.volume_change_pct == null ? "closed_changed" : "repaired";
}

/** "+10.4%", "−0.3%", "0.0%". */
export function signedPct(x: number): string {
  const r = Math.round(x * 10) / 10;
  if (r === 0) return "0.0%";
  return `${r > 0 ? "+" : "−"}${Math.abs(r).toFixed(1)}%`;
}

function mm(x: number): string {
  return `${Math.round(x * 10) / 10} mm`;
}

function count(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
}

/** What was open, as one line: "A missing face, an opening 20 mm across, and 1 smaller (6 mm) · 945 open edges". */
export function openingsLine(o: RepairOpenings | null | undefined): string | null {
  if (!o || o.kind === "none") return null;
  const edges = count(o.open_edges, "open edge");
  if (o.kind === "seams") return `Faces that touch but aren’t joined · ${edges}, ${o.welded_edges.toLocaleString("en-US")} of them on top of another`;
  if (o.kind === "surface") return `A surface with no thickness, ${o.largest_mm != null ? `${mm(o.largest_mm)} across` : "open all round"} · ${edges}`;
  if (o.kind === "face") {
    const rest = o.sizes_mm.slice(1, 4);
    const more = o.loops - 1;
    const tail = more > 0 ? `, and ${more} smaller${rest.length ? ` (${rest.map(mm).join(", ")}${more > rest.length ? ", …" : ""})` : ""}` : "";
    return `A missing face, an opening ${o.largest_mm != null ? mm(o.largest_mm) : "the size of a face"} across${tail} · ${edges}`;
  }
  return `${count(o.loops, "small gap")}${o.largest_mm != null ? `, the largest ${mm(o.largest_mm)} across` : ""} · ${edges}`;
}

/** The "what was open" line only where the outcome sentence doesn't already say it. */
export function openingsNote(kind: RepairOutcomeKind, o: RepairOpenings | null | undefined): string | null {
  if (kind === "repaired" || kind === "closed_changed" || kind === "not_needed") return null;
  if (!o || (o.kind !== "gaps" && o.kind !== "seams")) return null;
  return openingsLine(o);
}

export interface RepairHead {
  chip: string;
  tone: "c-ok" | "c-warn" | "c-bad";
  title: string;
}

/** The chip and headline for an outcome. */
export function repairHead(kind: RepairOutcomeKind, pct: number | null | undefined): RepairHead {
  switch (kind) {
    case "repaired":
      return { chip: "Repaired", tone: "c-ok", title: "Repaired: a closed solid now" };
    case "closed_changed":
      return { chip: "Closed · shape changed", tone: "c-warn", title: pct != null ? `Closed, but the volume changed ${signedPct(pct)}` : "Closed, but the change in shape is unknown" };
    case "partly":
      return { chip: "Partly closed", tone: "c-warn", title: "Partly closed: still not a solid" };
    case "not_needed":
      return { chip: "Nothing to repair", tone: "c-ok", title: "Already a closed solid" };
    default:
      return { chip: "Not repaired", tone: "c-bad", title: "Not repaired" };
  }
}

export type NextStep =
  | { kind: "heal"; label: string; why: string }
  | { kind: "cad"; label: string; why: string }
  | { kind: "upload"; label: string; why: string };

/**
 * The next best things to do after a repair, best first. `canHeal`: the server
 * offers its B-rep sewing for this part's open shell (GET /parts/{hash}/fixes).
 * Sewing joins faces that touch; it can't make a face that isn't there, so it is
 * never offered for a missing face or a surface.
 */
export function nextSteps(kind: RepairOutcomeKind, o: RepairOpenings | null | undefined, ctx: { brep: boolean; canHeal: boolean }): NextStep[] {
  if (kind === "repaired" || kind === "not_needed") return [];
  const k = o?.kind ?? "gaps";
  const out: NextStep[] = [];
  if (ctx.brep && ctx.canHeal && (k === "seams" || k === "gaps"))
    out.push({ kind: "heal", label: "Sew the faces into a solid", why: "ScaleCAD joins the STEP or IGES faces themselves, on a copy. Exact where mesh repair approximates." });
  const cad =
    kind === "closed_changed"
      ? "Close the opening in your CAD tool to keep the design’s shape, then export the solid."
      : k === "surface"
        ? "Thicken the surface, or export the solid body instead of surfaces."
        : k === "face"
          ? "Rebuild the missing face (fill or patch it), knit the faces into a solid, then export it."
          : "Heal or knit the faces into a solid, then export the solid body.";
  out.push({ kind: "cad", label: "Steps for your CAD tool", why: cad });
  out.push({ kind: "upload", label: "Upload a fixed file", why: "Checked like any upload and saved as a new part." });
  return out;
}

/** A repair request the server refused before running it, in plain words. */
export function repairRefusal(status: number, body: unknown, fallback: string): { msg: string; limit: boolean } {
  const b = body as { code?: unknown; message?: unknown; detail?: unknown } | null;
  const d = (b?.detail && typeof b.detail === "object" ? b.detail : b) as { code?: unknown; message?: unknown } | null;
  if (status === 429 && d?.code === "free_tool_limit" && typeof d.message === "string") return { msg: `${d.message} Pro and Pilot plans don’t have this limit.`, limit: true };
  if (status === 404) return { msg: "This part’s file isn’t kept with the record, so ScaleCAD can’t repair it from here. Choose the file to repair it.", limit: false };
  return { msg: fallback, limit: false };
}
