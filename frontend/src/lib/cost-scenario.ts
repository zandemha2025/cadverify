import type { CostOptions } from "@/lib/api";
import type { workspaceSelection, WorkspaceRoute } from "./cost-views.ts";

/** Capture the displayed selection and the submitted inputs, not the editable draft. */
export function captureCostScenario(
  selection: ReturnType<typeof workspaceSelection>,
  submitted: CostOptions,
  shopName?: string,
) {
  const { recommendation, quantity, estimate } = selection;
  if (!recommendation || quantity == null) return null;
  const route: WorkspaceRoute = { process: recommendation.curve.process,
    material: recommendation.curve.material, quantity };
  const overrides = { ...submitted.overrides };
  const count = Object.keys(overrides).length;
  return {
    label: `${shopName ?? "Generic"}${count ? ` · ${count} ovr` : ""} · qty ${quantity.toLocaleString()}${estimate?.quantity === quantity ? "" : " · approx."}`,
    unitCost: recommendation.unitCost,
    process: route.process,
    route,
    opts: { ...submitted, overrides },
  };
}
