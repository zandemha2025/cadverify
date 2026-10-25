import type { CostEstimate, CostReport } from "./api";
import { procLabel } from "./status.ts";
import { readVerification, verificationForRoute } from "./verify/verification.ts";

export const COST_DISPOSITIONS = [
  { key: "inhouse", label: "Make in-house" },
  { key: "outside", label: "Make outside" },
  { key: "acquire", label: "Acquire capability" },
  { key: "redesign", label: "Redesign" },
  // Bought as today, from the supplier the organization buys it from, at its current price.
  { key: "supplier", label: "Keep buying from our supplier" },
] as const;

export type CostDisposition = (typeof COST_DISPOSITIONS)[number]["key"];
/** The route an outcome was recorded at; "Keep buying from our supplier" names no route
 *  (`supplier: true`, the quantity and the price paid today, when known). */
export type CostDispositionBasis = Pick<CostEstimate, "process" | "material" | "quantity"> & {
  supplier?: boolean;
  usd_each?: number | null;
  price_source?: "you" | "parts_list" | null;
};

/** Outcomes that buy the part instead of making it on a machine of yours. */
export function isBuyOutcome(disposition: string | null | undefined): boolean {
  return disposition === "outside" || disposition === "supplier";
}

export function costDispositionBasisLabel(basis: CostDispositionBasis | null | undefined): string {
  if (basis?.supplier) {
    const qty = basis.quantity ? ` · qty ${basis.quantity.toLocaleString("en-US")}` : "";
    const price = basis.usd_each != null ? ` · $${basis.usd_each.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} each` : " · no price entered";
    return `From your supplier${price}${qty}`;
  }
  return basis ? `${procLabel(basis.process)} · ${basis.material} · qty ${basis.quantity.toLocaleString("en-US")}`
    : "Process and quantity were not recorded.";
}

export function inhouseDispositionError(report: CostReport | null, estimate: CostEstimate | null): string | null {
  if (!estimate) return "Select a computed quantity before recording Make in-house.";
  if (report?.status === "GEOMETRY_INVALID" || estimate.dfm_ready !== true || estimate.dfm_verdict === "fail"
      || estimate.environment_excluded || estimate.dfm_blockers?.length) {
    return "Route DFM is blocked. Make in-house stays locked until revised CAD passes; record Redesign, Make outside, or Acquire capability instead.";
  }
  const fit = verificationForRoute(readVerification(report), estimate.process);
  if (fit?.verdict !== "makeable_in_house" && fit?.verdict !== "makeable_with_secondary_op") {
    return "Owned-machine fit is not verified for this route. Declare a fitting machine and re-verify before recording Make in-house.";
  }
  return null;
}

export const COST_DISPOSITION_NOTE_MAX_LENGTH = 1000;

export function costDispositionLabel(
  disposition: CostDisposition | null | undefined
): string | null {
  return (
    COST_DISPOSITIONS.find((option) => option.key === disposition)?.label ?? null
  );
}

export function isCostDisposition(value: unknown): value is CostDisposition {
  return COST_DISPOSITIONS.some((option) => option.key === value);
}
