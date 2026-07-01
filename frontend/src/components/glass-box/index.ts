/**
 * Glass-box component library — the data-dense, provenance-first components this
 * product lives on. Every export renders the engine's real report_to_dict
 * fields; nothing prints a fake-exact price or a fabricated accuracy figure.
 */

export { ProvenanceChip, ProvenanceDot, ProvenanceLegend } from "./provenance";
export {
  ConfidenceInterval,
  ConfidenceTrack,
  ConfidenceLabel,
  ConfidenceChip,
} from "./confidence";
export { NumberReadout } from "./readout";
export { DriverBreakdown, type DriverRateEditor } from "./driver-breakdown";
export { AssumptionGrid } from "./assumptions";
export {
  ProcessComparison,
  type CompareRow,
  type CompareCell,
} from "./process-comparison";
export { RoutingCard, DfmMatrix } from "./routing";
export {
  CalibrationBar,
  type CalibrationRate,
  type CalibrationShop,
} from "./calibration";
export {
  RoleLens,
  ROLES,
  roleById,
  type RoleId,
  type RoleDef,
  type Density,
} from "./role-lens";
export { DecisionHeadline, RedesignBanner } from "./decision";

// The make-vs-buy / crossover chart already lives in cost/ and is theme-aware.
export { BreakevenChart as CrossoverChart } from "@/components/cost/BreakevenChart";
