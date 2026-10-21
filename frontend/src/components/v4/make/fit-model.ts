/**
 * Fit in context (board F2) rules, kept pure so they can be tested: who may use
 * it (asked before any file moves), file kinds and units, the XYZ nudge, the
 * seating words, and how the measured result reads. Every number comes from
 * POST /validate/fit; nothing here measures geometry.
 */
import type { FitResult } from "../../../lib/verify/context-fit";

export interface FitCapability {
  enabled: boolean;
  paid_access: boolean;
  can_submit: boolean;
  available: boolean;
}

/** What the capability probe answered: the body, "missing" (a server without the probe), or an error. */
export type CapabilityAnswer = { kind: "loading" } | { kind: "ok"; cap: FitCapability } | { kind: "missing" } | { kind: "error"; message: string };

export type FitAccess = "loading" | "off" | "viewer" | "on" | "error";

/**
 * Access first: the server setting, then the role. The tool is on every plan,
 * the free trial included, so the plan doesn't decide it (``paid_access`` is
 * always true from the server). A server without the probe (older API) is
 * treated as not offering the tool.
 */
export function resolveAccess(answer: CapabilityAnswer, canMutate: boolean): FitAccess {
  if (answer.kind === "loading") return "loading";
  if (answer.kind === "error") return "error";
  if (answer.kind === "missing") return "off";
  const c = answer.cap;
  if (!c.enabled) return "off";
  if (!c.can_submit || !canMutate) return "viewer";
  return "on";
}

export const FIT_ACCEPT = ".stl,.obj,.3mf,.step,.stp,.iges,.igs";

export function isFitFile(name: string): boolean {
  return /\.(stl|obj|3mf|step|stp|iges|igs)$/i.test(name);
}

/** STL and OBJ carry no units; the user says which units they were exported in. */
export function needsUnits(name: string): boolean {
  return /\.(stl|obj)$/i.test(name);
}

export function fileKind(name: string): string {
  const ext = name.split(".").pop()?.toUpperCase() ?? "";
  if (ext === "STP") return "STEP";
  if (ext === "IGS") return "IGES";
  return ext;
}

export function sizeText(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024).toLocaleString("en-US")} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** "STL · 33,992 faces" once the preview reported a face count, else "STL · 1.2 MB". */
export function fileSub(file: { name: string; size: number }, faces: number | null): string {
  const kind = fileKind(file.name);
  return faces != null ? `${kind} · ${faces.toLocaleString("en-US")} faces` : `${kind} · ${sizeText(file.size)}`;
}

export type Nudge = [string, string, string];

export function nudgeInvalid(n: Nudge): [boolean, boolean, boolean] {
  return n.map((v) => v.trim() === "" || !Number.isFinite(Number(v))) as [boolean, boolean, boolean];
}

export function nudgeValues(n: Nudge): [number, number, number] {
  return n.map((v) => Number(v)) as [number, number, number];
}

/** Row-major 4×4 translation, the transform the server applies for a shared frame plus nudge. */
export function translation([x, y, z]: [number, number, number]): number[][] {
  return [
    [1, 0, 0, x],
    [0, 1, 0, y],
    [0, 0, 1, z],
    [0, 0, 0, 1],
  ];
}

export type Seating = "shared_frame" | "auto";

export function seatMeta(seating: Seating): string {
  return seating === "shared_frame" ? "Seated from the assembly file" : "Seated automatically";
}

/** The line under the stage: how the pair was placed for the measurement. */
export function seatingLine(result: Pick<FitResult, "seating"> | null): string {
  if (!result) return "Results withheld until this pair is checked.";
  const nudged = (result.seating.manual_nudge_mm ?? []).some((v) => v !== 0);
  if (nudged)
    return result.seating.accepted && result.seating.method !== "shared_frame" ? "Automatically aligned, then offset by you." : "Position set by you.";
  if (result.seating.method === "shared_frame") return "Shared CAD frame: both files keep their own coordinates.";
  return result.seating.accepted ? "Automatically aligned surfaces. Check orientation and fit." : "Couldn’t seat this with confidence. Shared frame kept; nudge to adjust.";
}

export function seatingWord(result: Pick<FitResult, "seating"> | null): string {
  if (!result) return "—";
  if (result.seating.method === "shared_frame") return "Shared frame";
  return result.seating.accepted ? "Aligned" : "Uncertain";
}

/** Millimetres (or mm³): three decimals under 1 so small values don't round to zero, else two. */
export function mm(v: number): string {
  if (!Number.isFinite(v)) return "—";
  const d = v > 0 && v < 1 ? 3 : 2;
  return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export const mm3 = mm;

export interface FitFigures {
  volume: string;
  gap: string;
  seating: string;
  overlap: boolean;
}

export function figures(result: FitResult | null): FitFigures {
  if (!result) return { volume: "—", gap: "—", seating: "—", overlap: false };
  return {
    volume: mm3(result.collision.volume_mm3),
    gap: mm(result.clearance.closest_sampled_gap_mm),
    seating: seatingWord(result),
    overlap: result.collision.intersects,
  };
}

/** Band for the closest-gap zone the server reports (at least 0.05 mm). */
export function bandText(result: FitResult): string {
  const band = (result.clearance.tight_zone as { band_mm?: number }).band_mm;
  const v = typeof band === "number" && Number.isFinite(band) && band > 0 ? band : 0.05;
  return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: v < 0.1 ? 3 : 2 });
}

export type FitView = "col" | "gap";

export interface Callout {
  title: string;
  value: string;
  next: string;
}

export function callout(result: FitResult, view: FitView, painted: boolean): Callout {
  const overlap = result.collision.intersects;
  if (view === "col") {
    const shell = result.collision.region?.render_geometry.available !== false;
    return {
      title: "◆ Collision",
      value: overlap ? `${mm3(result.collision.volume_mm3)} mm³ measured overlap` : "No measured overlap",
      next: overlap
        ? shell
          ? "Move the part or change the overlapping geometry, then check again."
          : "The intersection shell is too large to draw; the marker shows its centre."
        : "No collision action is needed for this position.",
    };
  }
  return {
    title: "△ Closest measured gap",
    value: overlap ? "0.00 mm · the parts overlap" : `${mm(result.clearance.closest_sampled_gap_mm)} mm · sampled`,
    next: overlap
      ? "Resolve the overlap before judging clearance."
      : painted
        ? `Blue faces are within ${bandText(result)} mm of the closest gap.`
        : "The blue marker is the centre of the closest-gap zone.",
  };
}

/** Faces can be painted only when the preview is the very mesh the fit measured (not decimated, one mesh). */
export function canPaintFaces(preview: { decimated: boolean } | null): boolean {
  return !!preview && !preview.decimated;
}

export function goHint(s: { measured: boolean; running: boolean; hasFiles: boolean; nudgeBad: boolean; changed: boolean }): string {
  if (s.running) return "Overlap volume and closest gap";
  if (s.measured) return "Measured on the submitted files";
  if (!s.hasFiles) return "Add both files";
  if (s.nudgeBad) return "Fix the offsets first";
  if (s.changed) return "Inputs changed since the last check";
  return "Overlap volume and closest gap";
}
