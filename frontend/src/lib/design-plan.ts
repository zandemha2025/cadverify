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
  fourCornerHoles: true,
  holeDiameter: 6,
  holeInset: 10,
};

function roundDimension(value: number): number {
  return Math.round((value + Number.EPSILON) * 1_000_000) / 1_000_000;
}

export function buildDesignPlan(form: DesignForm): DesignPlan {
  if (form.kind === "plate") {
    const x = form.width / 2 - form.holeInset;
    const y = form.depth / 2 - form.holeInset;
    return {
      kind: "plate",
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
    };
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
  return {
    kind: "enclosure",
    width_mm: form.width,
    depth_mm: form.depth,
    height_mm: form.height,
    wall_thickness_mm: form.wallThickness,
  };
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
  };
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
  if (form.kind === "plate" && form.fourCornerHoles) {
    if (form.holeInset <= form.holeDiameter / 2 + 1) {
      return "Hole inset must leave at least 1 mm of material at the edge.";
    }
    if (form.holeInset >= Math.min(form.width, form.depth) / 2) {
      return "Hole inset must be smaller than half the plate width and depth.";
    }
  }
  return null;
}
