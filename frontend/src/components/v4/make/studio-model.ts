/**
 * Design Studio (board F1) words and numbers, kept pure so they can be tested:
 * template fields and limits, design and revision status, the interpreter's
 * answer, geometry facts, and the revision diff rows. Every number shown comes
 * from the server's revision record; nothing here estimates geometry.
 */
import type { Design, DesignInterpretation, DesignRevision, DesignRevisionComparison, RevisionDiffValue } from "../../../lib/designs-api";
import { MAX_DRAFT_DEG, supportsDraft, type DesignForm, type TemplateKind } from "../../../lib/design-plan.ts";

export const TEMPLATES: { kind: TemplateKind; label: string; desc: string }[] = [
  { kind: "plate", label: "Mounting plate", desc: "Flat stock with optional corner holes" },
  { kind: "bracket", label: "L bracket", desc: "Joined base and upright flange" },
  { kind: "enclosure", label: "Open enclosure", desc: "Base and four walls, open at the top" },
];

export function kindLabel(kind: string | null | undefined): string {
  return TEMPLATES.find((t) => t.kind === kind)?.label ?? "Design";
}

export type FieldKey = "width" | "depth" | "height" | "thickness" | "wallThickness" | "draftAngle";
export interface FieldSpec {
  key: FieldKey;
  label: string;
  min: number;
  max: number;
  step: number;
  lim: string;
  /** "°" for an angle; millimetres otherwise. */
  unit?: "°";
  /** One line shown beside the field. */
  note?: string;
}

/** The dimension fields each template takes, with the same limits the server validates. */
export function fieldsFor(kind: TemplateKind): FieldSpec[] {
  const big = kind === "enclosure" ? 20 : 10;
  const w: FieldSpec = { key: "width", label: "Width, mm", min: big, max: 1000, step: 1, lim: `${big} to 1,000` };
  const d: FieldSpec = { key: "depth", label: "Depth, mm", min: big, max: 1000, step: 1, lim: `${big} to 1,000` };
  const h: FieldSpec = { key: "height", label: "Height, mm", min: 10, max: 1000, step: 1, lim: "10 to 1,000" };
  const t: FieldSpec = { key: "thickness", label: "Thickness, mm", min: 0.5, max: 100, step: 0.5, lim: "0.5 to 100" };
  const wall: FieldSpec = { key: "wallThickness", label: "Wall, mm", min: 0.5, max: 50, step: 0.5, lim: "0.5 to 50" };
  if (kind === "plate") return [w, d, t];
  if (kind === "bracket") return [w, d, h, t];
  return [w, d, h, wall];
}

/** The draft setting, for the templates whose side walls release along +Z (plate, enclosure). */
export function draftField(kind: TemplateKind): FieldSpec | null {
  if (!supportsDraft(kind)) return null;
  return {
    key: "draftAngle",
    label: "Draft, °",
    min: 0,
    max: MAX_DRAFT_DEG,
    step: 0.5,
    lim: `0 to ${MAX_DRAFT_DEG}`,
    unit: "°",
    note: "Tapers the side walls so the part releases from a mold.",
  };
}

/** A field value outside its limits, as a sentence, or null. */
export function fieldProblem(form: DesignForm): string | null {
  const draft = draftField(form.kind);
  for (const f of [...fieldsFor(form.kind), ...(draft ? [draft] : [])]) {
    const v = form[f.key];
    const name = f.label.replace(/, (mm|°)$/, "");
    if (!Number.isFinite(v)) return `${name} needs a number.`;
    if (v < f.min || v > f.max) return `${name} must be ${f.lim}${f.unit === "°" ? "°" : " mm"}.`;
  }
  if (form.kind === "plate" && form.fourCornerHoles) {
    if (!Number.isFinite(form.holeDiameter) || form.holeDiameter < 1 || form.holeDiameter > 100) return "Hole diameter must be 1 to 100 mm.";
    if (!Number.isFinite(form.holeInset) || form.holeInset < 2 || form.holeInset > 500) return "Edge inset must be 2 to 500 mm.";
  }
  return null;
}

export type Tone = "ok" | "warn" | "bad" | "unk";

export function designChip(status: Design["status"]): { tone: Tone; label: string } {
  if (status === "ready") return { tone: "ok", label: "Ready" };
  if (status === "failed") return { tone: "bad", label: "Needs attention" };
  if (status === "archived") return { tone: "unk", label: "Archived" };
  return { tone: "unk", label: "Generating" };
}

export function revisionStatusWord(status: DesignRevision["status"]): string {
  if (status === "ready") return "Ready";
  if (status === "failed") return "Failed";
  if (status === "generating") return "Generating";
  return "Queued";
}

export function revisionSub(rev: Pick<DesignRevision, "status" | "number">, current: number): string {
  return revisionStatusWord(rev.status) + (rev.number === current ? " · current" : "");
}

/** "Viewing R2 · current" / "Viewing R1 · current is R2". */
export function viewText(view: number, current: number): string {
  return view === current ? `Viewing R${view} · current` : `Viewing R${view} · current is R${current}`;
}

export type InterpretView = { tone: Tone; label: string; text: string };

export const INTERPRET_IDLE: InterpretView = {
  tone: "unk",
  label: "Local rules, no AI",
  text: "Name a plate, L bracket or open enclosure with mm dimensions.",
};

/** The status line under the description box, in the server's own words. */
export function interpretView(result: DesignInterpretation): InterpretView {
  if (result.status === "ready") {
    // de-24: what the description asked for that the template can't draw is said, not dropped.
    const skipped = result.not_applied ?? [];
    return {
      tone: skipped.length ? "warn" : "ok",
      label: skipped.length ? `Ready, without ${skipped.join(" or ")}: ${kindLabel(result.kind)}` : `Ready: ${kindLabel(result.kind)}`,
      text: ["Local rules, no AI", ...result.assumptions].join(" · "),
    };
  }
  return { tone: "warn", label: "Needs input", text: result.message };
}

export function formatBytes(value: number | null | undefined): string {
  if (!value) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024).toLocaleString("en-US")} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function trim(n: number, digits = 2): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function envelopeText(bbox: number[] | null | undefined): string {
  if (!bbox || bbox.length < 3 || bbox.some((v) => !Number.isFinite(v))) return "—";
  return `${bbox.slice(0, 3).map((v) => trim(v, 1)).join(" × ")} mm`;
}

export function volumeText(cm3: number | null | undefined): string {
  return cm3 == null || !Number.isFinite(cm3) ? "—" : cm3.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function countText(n: number | null | undefined): string {
  return n == null || !Number.isFinite(n) ? "—" : Math.round(n).toLocaleString("en-US");
}

/** One diff value as text: numbers trimmed, lists and objects as JSON, missing as a dash. */
export function diffValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return trim(value, 3);
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "yes" : "no";
  return JSON.stringify(value);
}

/** A signed change: "+2", "−1.5", "0"; a dash when the server gave no numeric delta. */
export function deltaText(delta: number | null): string {
  if (delta == null || !Number.isFinite(delta)) return "—";
  if (delta === 0) return "0";
  return (delta > 0 ? "+" : "−") + trim(Math.abs(delta), 3);
}

export interface DiffRow {
  path: string;
  before: string;
  after: string;
  change: string;
}

export function diffRows(rows: RevisionDiffValue[]): DiffRow[] {
  return rows.map((r) => ({ path: r.path, before: diffValue(r.before), after: diffValue(r.after), change: deltaText(r.delta) }));
}

export function sameRevisionPair(from: number | null, to: number | null): boolean {
  return from != null && from === to;
}

/** Default compare pair: the two newest ready revisions (older → newer). */
export function defaultPair(revs: Pick<DesignRevision, "number" | "status">[]): [number, number] | null {
  const ready = revs.filter((r) => r.status === "ready").map((r) => r.number).sort((a, b) => a - b);
  if (ready.length < 2) return null;
  return [ready[ready.length - 2], ready[ready.length - 1]];
}

/** The check page link that opens one exact revision: `?design=<id>&revision=<n>`. */
export function checkHref(base: string, designId: string, revision: number): string {
  return `${base}?${new URLSearchParams({ design: designId, revision: String(revision) }).toString()}`;
}

export type ComparisonSide = DesignRevisionComparison["before"];
