/**
 * v4 moments: the shared interrupt and notice components every screen uses.
 * Each file documents its props at the top.
 *
 * - X5 pilot gate:      PilotGate, usePilotAccess, isPaidAccessError
 * - X3 out of checks:   OutOfChecks, useUsage
 * - X4 can't read:      CantReadSheet, CadToolSteps, NothingToDraw, cantReadCopy
 * - X11 banners:        Banner + SignedOutBanner, FreeChecksUsedBanner, BusyBanner, CantReadBanner,
 *                       DesignImportBanner, CheckInterruptedBanner, CostFailedBanner, CostBlockedBanner,
 *                       ProBanner, PreviewFailed, OrgErrorBanner, NoActiveOrgBanner, NotInOrgBanner, PageError
 * - X11 toasts:         useToasts, ToastStack
 * - X11 rates chip:     RatesChip
 * - X2 phone check:     PhoneGate (sheet), PhoneGateView (whole screen), MOMENT_ROUTES.phone (/app/phone)
 * - Held part:          useHeldPart (the part added on the sign-in screen, for the signed-in account)
 */
export { PilotGate, usePilotAccess, isPaidAccessError, PILOT_INCLUDES, PILOT_PLAN_FACTS, PILOT_HREF, type PilotFeature, type PilotAccess } from "./pilot-gate";
export { OutOfChecks, useUsage, type CheckUsage } from "./out-of-checks";
export { CantReadSheet, CadToolSteps, NothingToDraw, cantReadCopy, type CantReadProblem } from "./cant-read";
export {
  Banner,
  SignedOutBanner,
  FreeChecksUsedBanner,
  BusyBanner,
  CantReadBanner,
  DesignImportBanner,
  CheckInterruptedBanner,
  CostFailedBanner,
  CostBlockedBanner,
  ProBanner,
  PreviewFailed,
  OrgErrorBanner,
  NoActiveOrgBanner,
  NotInOrgBanner,
  PageError,
  type BannerTone,
} from "./banners";
export { useToasts, ToastStack, type ToastOptions, type ToastItem } from "./toasts";
export { RatesChip, ratesState, ratesLabel } from "./rates-chip";
export { PhoneGate, PhoneGateView, PartGlyph } from "./phone-gate";
export { useHeldPart } from "./held-part";
export { MOMENT_ROUTES } from "./routes";
