import type { Design, DesignPlan } from "@/lib/designs-api";

export type TemplateKind = DesignPlan["kind"];

export type DesignForm = {
  name: string;
  designNote: string;
  kind: TemplateKind;
  width: number;
  depth: number;
  height: number;
  thickness: number;
  wallThickness: number;
  /** Degrees; 0 keeps straight side walls. Only the plate and the enclosure take it. */
  draftAngle: number;
  fourCornerHoles: boolean;
  holeDiameter: number;
  holeInset: number;
};

export const DEFAULT_DESIGN_FORM: DesignForm = {
  name: "Mounting plate",
  designNote: "",
  kind: "plate",
  width: 80,
  depth: 50,
  height: 60,
  thickness: 6,
  wallThickness: 3,
  draftAngle: 0,
  fourCornerHoles: true,
  holeDiameter: 6,
  holeInset: 10,
};

/** The templates whose side walls release along +Z and take a draft angle (backend designs/schema.py). */
export const DRAFT_KINDS: readonly TemplateKind[] = ["plate", "enclosure"];
export const MAX_DRAFT_DEG = 10;

export function supportsDraft(kind: TemplateKind): boolean {
  return DRAFT_KINDS.includes(kind);
}

/** A plan's draft in degrees (a stored plan leaves out a zero draft); null for a template without one. */
export function draftAngleOf(plan: DesignPlan): number | null {
  if (plan.kind !== "plate" && plan.kind !== "enclosure") return null;
  return plan.draft_angle_deg ?? 0;
}

/** Sideways lean of a wall `height` mm tall at `deg` degrees of draft. */
function draftRun(height: number, deg: number): number {
  return height * Math.tan((deg * Math.PI) / 180);
}

function withDraft<T extends object>(plan: T, deg: number): T & { draft_angle_deg?: number } {
  return deg > 0 ? { ...plan, draft_angle_deg: deg } : plan;
}

function roundDimension(value: number): number {
  return Math.round((value + Number.EPSILON) * 1_000_000) / 1_000_000;
}

export function buildDesignPlan(form: DesignForm): DesignPlan {
  if (form.kind === "plate") {
    const x = form.width / 2 - form.holeInset;
    const y = form.depth / 2 - form.holeInset;
    return withDraft({
      kind: "plate" as const,
      width_mm: form.width,
      depth_mm: form.depth,
      thickness_mm: form.thickness,
      holes: form.fourCornerHoles
        ? [
            { x_mm: -x, y_mm: -y, diameter_mm: form.holeDiameter },
            { x_mm: x, y_mm: -y, diameter_mm: form.holeDiameter },
            { x_mm: x, y_mm: y, diameter_mm: form.holeDiameter },
            { x_mm: -x, y_mm: y, diameter_mm: form.holeDiameter },
          ]
        : [],
    }, form.draftAngle);
  }
  if (form.kind === "bracket") {
    return {
      kind: "bracket",
      width_mm: form.width,
      depth_mm: form.depth,
      height_mm: form.height,
      thickness_mm: form.thickness,
    };
  }
  return withDraft({
    kind: "enclosure" as const,
    width_mm: form.width,
    depth_mm: form.depth,
    height_mm: form.height,
    wall_thickness_mm: form.wallThickness,
  }, form.draftAngle);
}

export function formFromDesign(design: Design): DesignForm {
  const plan = design.revision?.plan;
  if (!plan) return { ...DEFAULT_DESIGN_FORM, name: design.name };
  return formFromPlan(
    plan,
    design.name,
    design.revision?.design_note ?? "",
  );
}

export function formFromPlan(
  plan: DesignPlan,
  name: string,
  designNote = "",
): DesignForm {
  if (plan.kind === "plate") {
    const first = plan.holes[0];
    return {
      ...DEFAULT_DESIGN_FORM,
      name,
      designNote,
      kind: "plate",
      width: plan.width_mm,
      depth: plan.depth_mm,
      thickness: plan.thickness_mm,
      draftAngle: plan.draft_angle_deg ?? 0,
      fourCornerHoles: plan.holes.length === 4,
      holeDiameter: first?.diameter_mm ?? DEFAULT_DESIGN_FORM.holeDiameter,
      holeInset: first
        ? roundDimension(
            Math.min(
              plan.width_mm / 2 - Math.abs(first.x_mm),
              plan.depth_mm / 2 - Math.abs(first.y_mm),
            ),
          )
        : DEFAULT_DESIGN_FORM.holeInset,
    };
  }
  if (plan.kind === "bracket") {
    return {
      ...DEFAULT_DESIGN_FORM,
      name,
      designNote,
      kind: "bracket",
      width: plan.width_mm,
      depth: plan.depth_mm,
      height: plan.height_mm,
      thickness: plan.thickness_mm,
    };
  }
  return {
    ...DEFAULT_DESIGN_FORM,
    name,
    designNote,
    kind: "enclosure",
    width: plan.width_mm,
    depth: plan.depth_mm,
    height: plan.height_mm,
    wallThickness: plan.wall_thickness_mm,
    draftAngle: plan.draft_angle_deg ?? 0,
  };
}

export function resolveViewedRevisionNo(
  current: number | null,
  revisions: Array<{ number: number }>,
  currentRevision: number,
  designChanged: boolean,
): number {
  if (designChanged) return currentRevision;
  return current && revisions.some((revision) => revision.number === current)
    ? current
    : currentRevision;
}

export function designRevisionRefreshKey(
  design: Pick<Design, "id" | "current_revision" | "status"> | null,
): string | null {
  return design
    ? `${design.id}:${design.current_revision}:${design.status}`
    : null;
}

export function validateDesignForm(form: DesignForm): string | null {
  if (!form.name.trim()) return "Give the design a name.";
  const positive = [form.width, form.depth, form.thickness];
  if (positive.some((value) => !Number.isFinite(value) || value <= 0)) {
    return "All dimensions must be positive numbers.";
  }
  if (form.kind !== "plate" && (!Number.isFinite(form.height) || form.height <= 0)) {
    return "Height must be a positive number.";
  }
  if (form.kind === "bracket" && form.thickness * 2 >= Math.min(form.width, form.height)) {
    return "Bracket thickness must be less than half its width and height.";
  }
  if (
    form.kind === "enclosure" &&
    (form.wallThickness * 4 >= Math.min(form.width, form.depth) ||
      form.wallThickness * 2 >= form.height)
  ) {
    return "Enclosure walls are too thick for the entered width, depth, or height.";
  }
  const draft = supportsDraft(form.kind) ? form.draftAngle : 0;
  if (!Number.isFinite(draft) || draft < 0 || draft > MAX_DRAFT_DEG) {
    return `Draft must be 0 to ${MAX_DRAFT_DEG}°.`;
  }
  if (form.kind === "enclosure" && draft > 0) {
    // Same rule as the server: the inside is narrowest on the floor.
    const lean = draftRun(form.height - form.wallThickness, draft) + form.wallThickness / Math.cos((draft * Math.PI) / 180);
    if (Math.min(form.width, form.depth) - 2 * lean <= 2 * form.wallThickness) {
      return "That draft leaves no room inside at the base. Use less draft or a thinner wall.";
    }
  }
  const run = form.kind === "plate" ? draftRun(form.thickness, draft) : 0;
  if (form.kind === "plate" && 4 * run >= Math.min(form.width, form.depth)) {
    return "That draft shrinks the plate’s top face below half its width or depth. Use less draft.";
  }
  if (form.kind === "plate" && form.fourCornerHoles) {
    if (form.holeInset <= form.holeDiameter / 2 + 1 + 2 * run) {
      return run > 0
        ? "Hole inset must leave at least 1 mm of material at the edge on the drafted top face."
        : "Hole inset must leave at least 1 mm of material at the edge.";
    }
    if (form.holeInset >= Math.min(form.width, form.depth) / 2) {
      return "Hole inset must be smaller than half the plate width and depth.";
    }
  }
  return null;
}
