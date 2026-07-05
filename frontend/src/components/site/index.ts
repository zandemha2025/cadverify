/**
 * Barrel for the dark-theater marketing-site FOUNDATION.
 *
 * Page builders import everything from `@/components/site`. These files are
 * SHARED FOUNDATION — page branches consume them but must NOT edit them
 * (see frontend/SITE-ROUTE-PLAN.md).
 */

export {
  SiteShell,
  SiteNav,
  SiteFooter,
  SiteFooterTagline,
  SITE_NAV,
  SITE_TAGLINE,
  PILOT_HREF,
} from "./site-shell";
export type { SiteNavProps } from "./site-shell";

export {
  PartStage,
  makeHomeChoreography,
} from "./part-stage";
export type {
  Choreography,
  StageFrame,
  StageObjects,
  PartStageProps,
  HomeChoreoRefs,
} from "./part-stage";

export {
  Eyebrow,
  DisplayHeading,
  Mono,
  MonoRow,
  ProvenanceChip,
  IllustrativeTag,
  InDevelopmentChip,
  HonestyBand,
  ScrollHint,
  Panel,
} from "./evidence";
export type { Provenance } from "./evidence";

export {
  lerp,
  clamp01,
  smooth,
  seg,
  measureSection,
  documentScrollProgress,
  applyCaptionReveal,
  scrollToSection,
  useRafLoop,
} from "@/lib/site/scroll-acts";
export type { ActMeasure } from "@/lib/site/scroll-acts";
